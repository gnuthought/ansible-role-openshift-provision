#!/usr/bin/python

import copy
import json
import os
import re
import tempfile
import traceback
import types

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = '''
---
module: openshift_provision

short_description: Provision OpenShift resources

description:
  - Manage OpenShift resources idempotently

options:
  action:
    description:
    - Action to perform on resource: apply, create, delete, patch, replace
    default: apply
    required: false
    aliases: []
  connection:
    description:
    - Dictionary of connection options, may include 'token', 'server', 'certificate_authority', 'insecure_skip_tls_verify', and 'oc_cmd'
    default: {}
    required: false
    aliases: []
  namespace:
    description:
    - Namespace in which to provision resource
    required: false
    aliases: []
  patch_type:
    description:
    - Type of patch to use with patch action
    default: strategic
    required: false
    aliases: []
  resource:
    description:
    - Resource definition
    required: true
    default: None
    aliases: []

extends_documentation_fragment: []

author:
- Johnathan Kupferer <jkupfere@redhat.com>
'''

EXAMPLES = '''
- name: Provision a PersistentVolume
  openshift_provision:
    action: replace
    namespace: example-project
    resource:
      apiVersion: v1
      kind: PersistentVolume
      metadata:
        creationTimestamp: null
        labels:
          foo: bar
        name: nfs-foo
      spec:
        accessModes:
        - ReadWriteMany
        capacity:
          storage: 10Gi
        nfs:
          path: /export/foo
          server: nfsserver.example.com
        persistentVolumeReclaimPolicy: Retain
'''

RETURN = '''
action:
  description: Action used to manage resource
  type: string
patch:
  description: JSONpatch describing change
  type: list
resource:
  description: Resource definition
  type: dict
'''

def make_field_patch(field, current, config):
    """
    Create JSONpatch list to describe differences between the current state
    and configured state.
    """
    # Adapted from jsonpatch to add current value
    def compare_values(path, value, other):
        if value == other:
            return
        if isinstance(value, dict) and isinstance(other, dict):
            for operation in compare_dict(path, value, other):
                yield operation
        elif isinstance(value, list) and isinstance(other, list):
            if list_is_set(value):
                for operation in compare_set_list(path, value, other):
                    yield operation
            elif list_has_keys(value):
                for operation in compare_keyed_list(path, value, other):
                    yield operation
            else:
                for operation in compare_list(path, value, other):
                    yield operation
        else:
            yield {
                'op': 'test',
                'path': '/'.join(path),
                'value': strip_value(value)
            }
            yield {
                'op': 'replace',
                'path': '/'.join(path),
                'value': strip_value(other)
            }

    def compare_dict(path, src, dst):
        for key in src:
            if key not in dst:
                yield {
                    'op': 'test',
                    'path': '/'.join(path + [key]),
                    'value': strip_value(src[key])
                }
                yield {
                    'op': 'remove',
                    'path': '/'.join(path + [key])
                }
                continue
            current = path + [key]
            for operation in compare_values(current, src[key], dst[key]):
                yield operation
        for key in dst:
            if key not in src:
                yield {
                    'op': 'add',
                    'path': '/'.join(path + [key]),
                    'value': strip_value(dst[key])
                }

    def compare_list(path, src, dst):
        lsrc, ldst = len(src), len(dst)
        for idx in range(min(lsrc, ldst)):
            current = path + [str(idx)]
            for operation in compare_values(current, src[idx], dst[idx]):
                yield operation
        if lsrc < ldst:
            for idx in range(lsrc, ldst):
                current = path + [str(idx)]
                yield {
                    'op': 'add',
                    'path': '/'.join(current),
                    'value': strip_value(dst[idx])
                }
        elif lsrc > ldst:
            for idx in reversed(range(ldst, lsrc)):
                yield {
                    'op': 'test',
                    'path': '/'.join(path + [str(idx)]),
                    'value': strip_value(src[idx])
                }
                yield {
                    'op': 'remove',
                    'path': '/'.join(path + [str(idx)])
                }

    def compare_keyed_list(path, src, dst):
        key_name = src[-1]['__key_name__']
        src_key_map = src[-1]['__key_map__']
        dst_key_map = dst[-1]['__key_map__']
        for src_idx in range(len(src)-2, -1, -1):
            current = path + [str(src_idx)]
            src_item = src[src_idx]
            dst_idx = dst_key_map.get(src_item[key_name], None)
            if dst_idx == None:
                yield {
                    'op': 'test',
                    'path': '/'.join(current),
                    'value': strip_value(src_item)
                }
                yield {
                    'op': 'remove',
                    'path': '/'.join(current)
                }
            else:
                for operation in compare_values(current, src_item, dst[dst_idx]):
                    yield operation
        for dst_item in dst[:-1]:
            if dst_item[key_name] not in src_key_map:
                yield {
                    'op': 'add',
                    'path': '/'.join(path + ['-']),
                    'value': strip_value(dst_item)
                }

    def compare_set_list(path, src, dst):
        for src_idx in range(len(src)-2, -1, -1):
            current = path + [str(src_idx)]
            src_item = src[src_idx]
            if src_item not in dst:
                yield {
                    'op': 'test',
                    'path': '/'.join(current),
                    'value': strip_value(src_item)
                }
                yield {
                    'op': 'remove',
                    'path': '/'.join(current)
                }
        for dst_item in dst[:-1]:
            if dst_item not in src:
                yield {
                    'op': 'add',
                    'path': '/'.join(path + ['-']),
                    'value': strip_value(dst_item)
                }

    return list(compare_values(['/' + field], current, config))

def set_dict_defaults(d, default):
    if d is None:
        d = default
    else:
        for k, v in default.items():
            if k not in d:
                d[k] = v

def normalize_cpu_units(cpu):
    cpu = str(cpu)
    if cpu[-1:] == 'm':
        return cpu
    else:
        return '%dm' % (int(cpu) * 1000)

def normalize_memory_units(memory):
    memory = str(memory)
    if memory[-1:] == 'm':
        # Very strange case, but OpenShift will use "m" unit to represent
        # thousandths of a byte
        return str(int(memory[:-1]) / 1000)
    elif memory[-2:] == 'Ki':
        return str(int(memory[:-2]) * 1024)
    elif memory[-1:] in ['k', 'K']:
        return str(int(memory[:-1]) * 1000)
    elif memory[-2:] == 'Mi':
        return str(int(memory[:-2]) * 1024 ** 2)
    elif memory[-1:] == 'M':
        return str(int(memory[:-1]) * 1000 ** 2)
    elif memory[-2:] == 'Gi':
        return str(int(memory[:-2]) * 1024 ** 3)
    elif memory[-1:] == 'G':
        return str(int(memory[:-1]) * 1000 ** 3)
    else:
        return memory

def normalize_resource_units(item):
    if 'memory' in item:
        item['memory'] = normalize_memory_units(item['memory'])
    if 'cpu' in item:
        item['cpu'] = normalize_cpu_units(item['cpu'])

def merge_dict(merged, patch, overwrite=True):
    """
    Given a dictionary and a patch, apply patch to the dictionary.
    The patch is given as a dictionary each key/value of which determines the
    handling:

    * Patch value is a dictionary, then this function is applied recursively.
    * Patch value is callable, such as a function, then this function is called
      with the dictionary value or None if the corresponding key is not in the
      merged dictionary.
    * Otherwise the patch value either provides an override value or default
      depending on value of overwrite.
    """
    if not merged:
        return {}
    for k, v in patch.items():
        if type(v) is dict:
            if not k in merged:
                merged[k] = copy.deepcopy(v)
            elif type(merged[k]) is dict:
                merge_dict(merged[k], v, overwrite)
            else:
                raise Exception(
                    "Unable to merge {} with dict".format(
                        type(merged[k]).__name__
                    )
                )
        elif callable(v):
            merged[k] = v(merged[k] if k in merged else None)
        elif overwrite or not k in merged:
            merged[k] = copy.deepcopy(v)

def mark_list_is_set(lst, key_name=None):
    lst.append({
        '__special_list_type__': 'set'
    })

def list_is_set(lst):
    return(
        len(lst) != 0 and
        type(lst[-1]) is dict and
        'set' == lst[-1].get('__special_list_type__', None)
    )

def mark_list_with_keys(lst, key_name):
    key_map = {}
    for idx, item in enumerate(lst):
        key_map[item[key_name]] = idx
    lst.append({
        '__special_list_type__': 'keyed',
        '__key_map__': key_map,
        '__key_name__': key_name
    })

def strip_value(lst):
    """Return value stripped of any special mutations"""
    if isinstance(lst, list) \
    and len(lst) > 0 \
    and type(lst[-1]) is dict \
    and '__special_list_type__' in lst[-1]:
        return lst[:-1]
    return lst

def list_has_keys(lst):
    return(
        len(lst) != 0 and
        type(lst[-1]) is dict and
        'keyed' == lst[-1].get('__special_list_type__', None)
    )

def normalize_BuildConfig_V1(build_config):
    set_dict_defaults(build_config, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(build_config['metadata'])
    normalize_BuildConfigSpec_V1(build_config['spec'])

def normalize_BuildConfigCustomStrategy_V1(strategy):
    set_dict_defaults(strategy, {
        'env': [],
        'from': {}
    })
    normalize_EnvVars_V1(strategy['env'])
    normalize_ObjectReference_V1(strategy['from'])

def normalize_BuildConfigDockerStrategy_V1(strategy):
    set_dict_defaults(strategy, {
        'env': [],
        'from': {}
    })
    normalize_EnvVars_V1(strategy['env'])
    normalize_ObjectReference_V1(strategy['from'])

def normalize_BuildConfigJenkinsPipelineStrategy_V1(strategy):
    set_dict_defaults(strategy, {
        'env': []
    })
    normalize_EnvVars_V1(strategy['env'])

def normalize_BuildConfigSpec_V1(spec):
    set_dict_defaults(spec, {
        'nodeSelector': None,
        'resources': {},
        'runPolicy': 'Serial',
        'source': {},
        'strategy': {},
        'triggers': [{'imageChange': {}}]
    })
    normalize_BuildConfigSource_V1(spec['source'])
    normalize_BuildConfigStrategy_V1(spec['strategy'])

def normalize_BuildConfigSource_V1(source):
    set_dict_defaults(source, {
        'contextDir': ''
    })
    if 'git' in source:
        normalize_BuildConfigSourceGit_V1(source['git'])

def normalize_BuildConfigSourceGit_V1(git):
    set_dict_defaults(git, {
        'ref': ''
    })

def normalize_BuildConfigSourceStrategy_V1(strategy):
    set_dict_defaults(strategy, {
        'env': [],
        'from': {}
    })
    normalize_EnvVars_V1(strategy['env'])
    normalize_ObjectReference_V1(strategy['from'])

def normalize_BuildConfigStrategy_V1(strategy):
    if 'customStrategy' in strategy:
        normalize_BuildConfigCustomStrategy_V1(strategy['customStrategy'])
    if 'dockerStrategy' in strategy:
        normalize_BuildConfigDockerStrategy_V1(strategy['dockerStrategy'])
    if 'jenkinsPipelineStrategy' in strategy:
        normalize_BuildConfigJenkinsPipelineStrategy_V1(strategy['jenkinsPipelineStrategy'])
    if 'sourceStrategy' in strategy:
        normalize_BuildConfigSourceStrategy_V1(strategy['sourceStrategy'])

def normalize_ClientIPConfig_V1(config):
    set_dict_defaults(config, {
        'timeoutSeconds': 10800
    })

def normalize_ClusterResourceQuota_V1(quota):
    set_dict_defaults(quota, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(quota['metadata'])
    normalize_ClusterResourceQuotaSpec_V1(quota['spec'])

def normalize_ClusterResourceQuotaSpec_V1(spec):
    set_dict_defaults(spec, {
        'quota': {}
    })
    normalize_ResourceQuotaSpec_V1(spec['quota'])

def normalize_ClusterRole_V1(role):
    set_dict_defaults(role, {
        'aggregationRule': {},
        'metadata': {},
        'rules': []
    })
    normalize_ObjectMeta_V1(role['metadata'])
    for rule in role['rules']:
        normalize_PolicyRule_V1(rule)

def normalize_ClusterRoleBinding_V1(role_binding):
    set_dict_defaults(role_binding, {
        'metadata': {},
        'roleRef': {},
        'subjects': []
    })
    normalize_ObjectMeta_V1(role_binding['metadata'])
    normalize_RoleRef_V1(role_binding['roleRef'])
    for subject in role_binding['subjects']:
        normalize_Subject_V1(subject)
    mark_list_is_set(role_binding['subjects'])

def normalize_Project_V1(project):
    set_dict_defaults(project, {
        'metadata': {}
    })
    normalize_ObjectMeta_V1(project['metadata'])


def normalize_ConfigMapVolumeSource_V1(value):
    set_dict_defaults(value, {
        'defaultMode': 0o644
    })

def normalize_Container_V1(container):
    set_dict_defaults(container, {
        'env': [],
        'imagePullPolicy': 'IfNotPresent',
        'livenessProbe': None,
        'ports': [],
        'readinessProbe': None,
        'resources': {},
        'securityContext': {},
        'terminationMessagePath': '/dev/termination-log',
        'terminationMessagePolicy': 'File',
        'volumeMounts': []
    })
    normalize_EnvVars_V1(container['env'])
    normalize_Probe_V1(container['livenessProbe'])
    normalize_ContainerPortList_V1(container['ports'])
    normalize_ResourceRequirements_V1(container['resources'])
    normalize_SecurityContext_V1(container['securityContext'])
    normalize_VolumeMountList_V1(container['volumeMounts'])
    normalize_Probe_V1(container['readinessProbe'])

def normalize_ContainerList_V1(container_list):
    for container in container_list:
        normalize_Container_V1(container)
    mark_list_with_keys(container_list, 'name')

def normalize_ContainerPort_V1(port):
    set_dict_defaults(port, {
        'protocol': 'TCP'
    })

def normalize_ContainerPortList_V1(port_list):
    for port in port_list:
        normalize_ContainerPort_V1(port)
    mark_list_with_keys(port_list, 'containerPort')

def normalize_CronJob_V1beta1(cron_job):
    set_dict_defaults(cron_job, {
        'metadata': {},
        'spec': {}
    })
    cron_job['status'] = None
    normalize_CronJobSpec_V1beta1(cron_job['spec'])

def normalize_CronJobSpec_V1beta1(spec):
    set_dict_defaults(spec, {
        'jobTemplate': {}
    })
    normalize_JobTemplateSpec_V1beta1(spec['jobTemplate'])

def normalize_DaemonSet_V1(daemon_set):
    set_dict_defaults(daemon_set, {
        'metadata': {},
        'spec': {}
    })
    daemon_set['status'] = None
    normalize_ObjectMeta_V1(daemon_set['metadata'])
    normalize_DaemonSetSpec_V1(daemon_set['spec'])

def normalize_DaemonSetSpec_V1(spec):
    set_dict_defaults(spec, {
        'revisionHistoryLimit': 10,
        'template': {}
    })
    normalize_PodTemplateSpec_V1(spec['template'])

def normalize_Deployment_V1(deployment):
    set_dict_defaults(deployment, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(deployment['metadata'])
    normalize_DeploymentSpec_V1(deployment['spec'])
    deployment['metadata']['annotations']['deployment.kubernetes.io/revision'] = 0
    deployment['status'] = None

def normalize_DeploymentConfig_V1(deployment_config):
    set_dict_defaults(deployment_config, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(deployment_config['metadata'])
    normalize_DeploymentConfigSpec_V1(deployment_config['spec'])

def normalize_DeploymentConfigSpec_V1(spec):
    set_dict_defaults(spec, {
        'revisionHistoryLimit': 10,
        'strategy': {},
        'template': {},
        'test': False,
        'triggers': [{"type": "ConfigChange"}]
    })
    normalize_DeploymentConfigStrategy_V1(spec['strategy'])
    normalize_PodTemplateSpec_V1(spec['template'])
    for trigger in spec['triggers']:
        normalize_DeploymentConfigTrigger_V1(trigger)

    # Ignore image value if there are ImageChange triggers
    image_change_trigger_container_names = []
    for trigger in spec['triggers']:
        if trigger['type'] == 'ImageChange':
            image_change_trigger_container_names.extend(
                trigger.get('imageChangeParams', {}).get('containerNames', [])
            )
    for container in spec['template']['spec']['containers'][:-1]:
        if container['name'] in image_change_trigger_container_names:
            container['image'] = ''

def normalize_DeploymentConfigStrategy_V1(strategy):
    set_dict_defaults(strategy, {
        'activeDeadlineSeconds': 21600,
        'resources': {}
    })
    if 'recreateParams' in strategy:
        normalize_DeploymentConfigStrategyRecreateParams_V1(strategy['recreateParams'])

def normalize_DeploymentConfigStrategyRecreateParams_V1(params):
    set_dict_defaults(params, {
        'timeoutSeconds': 600
    })

def normalize_DeploymentConfigTrigger_V1(trigger):
    if 'imageChangeParams' in trigger:
        normalize_DeploymentConfigTriggerImageChangeParams_V1(trigger['imageChangeParams'])

def normalize_DeploymentConfigTriggerImageChangeParams_V1(params):
    set_dict_defaults(params, {
        'from': {}
    })
    normalize_ObjectReference_V1(params['from'])
    params['lastTriggeredImage'] = ''

def normalize_DeploymentSpec_V1(spec):
    set_dict_defaults(spec, {
        'progressDeadlineSeconds': 600,
        'revisionHistoryLimit': 10,
        'template': {}
    })
    normalize_PodTemplateSpec_V1(spec['template'])

def normalize_EnvVars_V1(env_list):
    for env in env_list:
        # Openshift drops the empty value strings, put those back to compare
        if 'value' not in env \
        and 'valueFrom' not in env:
            env['value'] = ''
    mark_list_with_keys(env_list, 'name')

def normalize_HorizontalPodAutoscaler(autoscaler):
    set_dict_defaults(autoscaler, {
        'metadata': {},
        'spec': {}
    })
    autoscaler['status'] = None
    normalize_ObjectMeta_V1(autoscaler['metadata'])
    autoscaler['metadata']['annotations']['autoscaling.alpha.kubernetes.io/conditions'] = ''

def normalize_HostPathVolumeSource_V1(host_path_source):
    set_dict_defaults(host_path_source, {
        'type': ''
    })

def normalize_HTTPGetAction_V1(value):
    set_dict_defaults(value, {
        'scheme': 'HTTP'
    })

def normalize_ImageStream_V1(image_stream):
    set_dict_defaults(image_stream, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(image_stream['metadata'])
    normalize_ImageStreamSpec_V1(image_stream['spec'])
    image_stream['metadata']['annotations']['openshift.io/image.dockerRepositoryCheck'] = ''

def normalize_ImageStreamSpec_V1(spec):
    set_dict_defaults(spec, {
        'dockerImageRepository': '',
        'lookupPolicy': {'local': False},
        'tags': []
    })
    for tag in spec['tags']:
        normalize_ImageStreamTag_V1(tag)

def normalize_ImageStreamTag_V1(tag):
    set_dict_defaults(tag, {
        'referencePolicy': {'type': 'Source'}
    })
    tag['generation'] = 0

def normalize_JobSpec_V1(spec):
    set_dict_defaults(spec, {
        'template': {}
    })
    normalize_PodTemplateSpec_V1(spec['template'])

def normalize_JobTemplateSpec_V1beta1(spec):
    set_dict_defaults(spec, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(spec['metadata'])
    normalize_JobSpec_V1(spec['spec'])

def normalize_LimitRange_V1(limit_range):
    set_dict_defaults(limit_range, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(limit_range['metadata'])
    normalize_LimitRangeSpec_V1(limit_range['spec'])

def normalize_LimitRangeSpec_V1(spec):
    set_dict_defaults(spec, {
        'limits': []
    })
    for limit in spec['limits']:
        for name, value in limit.items():
            if name not in ('type', 'maxLimitRequestRatio'):
                normalize_resource_units(value)

def normalize_NetworkPolicy_V1(policy):
    set_dict_defaults(policy, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(policy['metadata'])
    normalize_NetworkPolicySpec_V1(policy['spec'])

def normalize_NetworkPolicySpec_V1(spec):
    set_dict_defaults(spec, {
        'egress': [],
        'ingress': [],
        'podSelector': {},
        'policyTypes': ['Ingress']
    })

    # "If no policyTypes are specified on a NetworkPolicy then by default
    # Ingress will always be set and Egress will be set if the NetworkPolicy
    # has any egress rules."
    # https://kubernetes.io/docs/concepts/services-networking/network-policies/
    if spec['egress'] and 'Egress' not in spec['policyTypes']:
        spec['policyTypes'].append('Egress')

    mark_list_is_set(spec['policyTypes'])
    for egress in spec['egress']:
        normalize_NetworkPolicyEgressRule_V1(egress)
    for ingress in spec['egress']:
        normalize_NetworkPolicyIngressRule_V1(ingress)

def normalize_NetworkPolicyEgressRule_V1(rule):
    if 'to' in rule:
        mark_list_is_set(rule['to'])
    if 'ports' in rule:
        for port in rule['ports']:
            normalize_NetworkPolicyPort_V1(port)
        mark_list_is_set(rule['ports'])

def normalize_NetworkPolicyIngressRule_V1(rule):
    if 'from' in rule:
        mark_list_is_set(rule['from'])
    if 'ports' in rule:
        for port in rule['ports']:
            normalize_NetworkPolicyPort_V1(port)
        mark_list_is_set(rule['ports'])

def normalize_NetworkPolicyPort_V1(port):
    set_dict_defaults(port, {
        'protocol': 'TCP'
    })

def normalize_ObjectMeta_V1(metadata):
    if metadata:
        set_dict_defaults(metadata, {
            'annotations': {}
        })
        metadata.update({
            'creationTimestamp': '',
            'generation': 0,
            'namespace': '',
            'resourceVersion': 0,
            'selfLink': '',
            'uid': ''
        })
        metadata['annotations']['kubectl.kubernetes.io/last-applied-configuration'] = ''

def normalize_ObjectReference_V1(ref):
    set_dict_defaults(ref, {
        'namespace': ''
    })

def normalize_PersistentVolume_V1(pv):
    set_dict_defaults(pv, {
        'metadata': {},
        'spec': {}
    })
    pv['status'] = None
    set_dict_defaults(pv['metadata'], {
        'finalizers': ['kubernetes.io/pv-protection']
    })
    normalize_ObjectMeta_V1(pv['metadata'])
    normalize_PersistentVolumeSpec_V1(pv['spec'])
    pv['metadata']['annotations']['pv.kubernetes.io/bound-by-controller'] = ''

def normalize_PersistentVolumeClaim_V1(pvc):
    set_dict_defaults(pvc, {
        'metadata': {},
        'spec': {}
    })
    set_dict_defaults(pvc['metadata'], {
        'finalizers': ['kubernetes.io/pvc-protection']
    })
    normalize_ObjectMeta_V1(pvc['metadata'])
    normalize_PersistentVolumeClaimSpec_V1(pvc['spec'])
    pvc['status'] = None
    pvc['metadata']['annotations']['pv.kubernetes.io/bind-completed'] = ''
    pvc['metadata']['annotations']['pv.kubernetes.io/bound-by-controller'] = ''
    pvc['metadata']['annotations']['volume.beta.kubernetes.io/storage-provisioner'] = ''

def normalize_PersistentVolumeClaimSpec_V1(spec):
    set_dict_defaults(spec, {
        'dataSource': None
    })
    spec['volumeName'] = ''

def normalize_PersistentVolumeSpec_V1(spec):
    set_dict_defaults(spec, {
        'persistentVolumeReclaimPolicy': 'Retain'
    })
    spec['claimRef'] = ''

def normalize_PodSpec_V1(spec):
    set_dict_defaults(spec, {
        'containers': [],
        'dnsPolicy': 'ClusterFirst',
        'restartPolicy': 'Always',
        'securityContext': {},
        'schedulerName': 'default-scheduler',
        'terminationGracePeriodSeconds': 30,
        'volumes': []
    })

    # ServiceAccount is deprecated in favor of serviceAccountName
    if 'serviceAccountName' in spec:
        spec['serviceAccount'] = spec['serviceAccountName']
    elif 'serviceAccount' in spec:
        spec['serviceAccountName'] = spec['serviceAccount']

    normalize_ContainerList_V1(spec['containers'])
    normalize_VolumeList_V1(spec['volumes'])

    # If pod template uses hostNetwork then ports on containers have
    # hostPort which defaults to containerPort
    if spec.get('hostNetwork', False):
        for container in spec['containers'][:-1]:
            for port in container['ports'][:-1]:
                if 'hostPort' not in port:
                    port['hostPort'] = port['containerPort']

def normalize_PodTemplateSpec_V1(pod_template):
    set_dict_defaults(pod_template, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(pod_template['metadata'])
    normalize_PodSpec_V1(pod_template['spec'])

def normalize_PolicyRule_V1(rule):
    for key in (
        'apiGroups',
        'nonResourceURLs',
        'resourceNames',
        'resources',
        'verbs'
    ):
        if rule.get(key, None) == None:
            rule[key] = []
        mark_list_is_set(rule[key])
    # Openshift policy rules may have attributeRestrictions, but these seem
    # to always be null? Remove for comparison.
    if 'attributeRestrictions' in rule and rule['attributeRestrictions'] == None:
        del rule['attributeRestrictions']



def normalize_Probe_V1(probe):
    if probe == None:
        return
    set_dict_defaults(probe, {
        'initialDelaySeconds': 30,
        'periodSeconds': 10,
        'successThreshold': 1,
        'failureThreshold': 3
    })
    if 'httpGet' in probe:
        normalize_HTTPGetAction_V1(probe['httpGet'])

def normalize_ResourceQuota_V1(quota):
    set_dict_defaults(quota, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(quota['metadata'])
    normalize_ResourceQuotaSpec_V1(quota['spec'])

def normalize_ResourceQuotaSpec_V1(spec):
    set_dict_defaults(spec, {
        'hard': {}
    })
    for item in ('requests.cpu', 'limits.cpu'):
        if item in spec['hard']:
            spec['hard'][item] = normalize_cpu_units(spec['hard'][item])
    for item in ('requests.memory', 'limits.memory'):
        if item in spec['hard']:
            spec['hard'][item] = normalize_memory_units(spec['hard'][item])

def normalize_ResourceRequirements_V1(resources):
    if not resources:
        return {}
    if 'limits' in resources:
        resources['limits'] = normalize_resource_units(resources['limits'])
    if 'requests' in resources:
        resources['requests'] = normalize_resource_units(resources['requests'])
    return resources

def normalize_Role_V1(role):
    set_dict_defaults(role, {
        'metadata': {},
        'rules': []
    })
    normalize_ObjectMeta_V1(role['metadata'])
    for rule in role['rules']:
        normalize_PolicyRule_V1(rule)

def normalize_RoleBinding_V1(role_binding):
    set_dict_defaults(role_binding, {
        'metadata': {},
        'roleRef': {},
        'subjects': []
    })
    normalize_ObjectMeta_V1(role_binding['metadata'])
    normalize_RoleRef_V1(role_binding['roleRef'])
    for subject in role_binding['subjects']:
        normalize_Subject_V1(subject)
    mark_list_is_set(role_binding['subjects'])

def normalize_RoleRef_V1(ref):
    set_dict_defaults(ref, {
        'apiGroup': 'rbac.authorization.k8s.io',
        'kind': 'ClusterRole'
    })

def normalize_Route_V1(route):
    set_dict_defaults(route, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(route['metadata'])
    normalize_RouteSpec_V1(route['spec'])
    route['status'] = None

    # If route host is generated, then need to blank out the host field to compare
    if '' == route['spec'].get('host', '') \
    or 'true' == route['metadata']['annotations'].get('openshift.io/host.generated'):
         route['spec']['host'] = ''
         route['metadata']['annotations']['openshift.io/host.generated'] = 'true'

def normalize_RouteSpec_V1(spec):
    set_dict_defaults(spec, {
        'to': {},
        'wildcardPolicy': 'None'
    })
    set_dict_defaults(spec['to'], {
        'weight': 100
    })

def normalize_SecretVolumeSource_V1(value):
    set_dict_defaults(value, {
        'defaultMode': 0o644
    })

def normalize_SecurityContext_V1(securityContext):
    set_dict_defaults(securityContext, {
        'privileged': False,
        'procMount': 'Default'
    })

def normalize_SecurityContextConstraints_V1(scc):
    # Sometimes SecurityContextConstraints come back with values of None
    # rather than an empty list.
    for key in (
        'allowedCapabilities',
        'defaultAddCapabilities',
        'groups',
        'requiredDropCapabilities',
        'users',
        'volumes'
    ):
        if scc.get(key, None) == None:
            scc[key] = []
        mark_list_is_set(scc[key])

def normalize_Service_V1(service):
    set_dict_defaults(service, {
        'metadata': {},
        'spec': {}
    })
    service['status'] = None
    normalize_ObjectMeta_V1(service['metadata'])
    normalize_ServiceSpec_V1(service['spec'])

    # Ignore dynamic cert signing annotations on secrets
    if 'service.alpha.openshift.io/serving-cert-secret-name' in service['metadata']['annotations']:
        service['metadata']['annotations']['service.alpha.openshift.io/serving-cert-signed-by'] = ''

def normalize_ServicePort_V1(port):
    set_dict_defaults(port, {
        'protocol': 'TCP'
    })

def normalize_ServicePortList_V1(port_list):
    for port in port_list:
        normalize_ServicePort_V1(port)
    mark_list_with_keys(port_list, 'port')

def normalize_ServiceSpec_V1(spec):
    set_dict_defaults(spec, {
        'ports': [],
        'sessionAffinity': 'None',
        'type': 'ClusterIP'
    })
    if spec['sessionAffinity'] == 'ClientIP':
        set_dict_defaults(spec, {
            'sessionAffinityConfig': {}
        })
    normalize_ServicePortList_V1(spec['ports'])
    if 'sessionAffinityConfig' in spec:
        normalize_SessionAffinityConfig_V1(spec['sessionAffinityConfig'])

def normalize_SessionAffinityConfig_V1(config):
    set_dict_defaults(config, {
        'clientIP': {}
    })
    normalize_ClientIPConfig_V1(config['clientIP'])

def normalize_StatefulSet_V1(stateful_set):
    set_dict_defaults(stateful_set, {
        'metadata': {},
        'spec': {}
    })
    normalize_ObjectMeta_V1(stateful_set['metadata'])
    normalize_StatefulSetSpec_V1(stateful_set['spec'])
    stateful_set['status'] = None

def normalize_StatefulSetSpec_V1(spec):
    set_dict_defaults(spec, {
        'replicas': 1,
        'revisionHistoryLimit': 10,
        'template': {},
        'volumeClaimTemplates': []
    })
    normalize_PodTemplateSpec_V1(spec['template'])
    for pvc in spec['volumeClaimTemplates']:
        normalize_PersistentVolumeClaim_V1(pvc)

def normalize_Subject_V1(subject):
    # Reconcile differences between OpenShift and kube group subjects
    # Remove apiGroup if set to default
    if subject.get('apiGroup', '') == 'rbac.authorization.k8s.io':
        del subject['apiGroup']
    # OpenShift uses SystemGroup when kubernetes uses Group
    if subject.get('kind', '') == 'SystemGroup':
        subject['kind'] = 'Group'

def normalize_Volume_V1(volume):
    if 'configMap' in volume:
        normalize_ConfigMapVolumeSource_V1(volume['configMap'])
    elif 'hostPath' in volume:
        normalize_HostPathVolumeSource_V1(volume['hostPath'])
    elif 'secret' in volume:
        normalize_SecretVolumeSource_V1(volume['secret'])

def normalize_VolumeList_V1(volumes):
    for volume in volumes:
        normalize_Volume_V1(volume)
    mark_list_with_keys(volumes, 'name')

def normalize_VolumeMountList_V1(volume_mount_list):
    mark_list_with_keys(volume_mount_list, 'name')

class OpenShiftProvision:
    def __init__(self, module):
        self.module = module
        self.changed = False
        self.action = module.params['action']
        self.fail_on_change = module.params['fail_on_change']
        self.patch = None
        self.patch_type = module.params['patch_type']
        self.resource = module.params['resource']
        self.generate_resources = module.params['generate_resources']

        if not 'kind' in self.resource:
            raise Exception('resource must define kind')
        if not 'metadata' in self.resource:
            raise Exception('resource must include metadata')
        if not 'name' in self.resource['metadata']:
            raise Exception('resource metadata must include name')

        if 'namespace' in self.resource['metadata']:
            self.namespace = self.resource['metadata']['namespace']
        elif 'namespace' in module.params:
            self.namespace = module.params['namespace']
            self.resource['metadata']['namespace'] = self.namespace

        connection = module.params['connection']
        if 'oc_cmd' in connection:
            self.oc_cmd = connection['oc_cmd'].split()
        else:
            self.oc_cmd = ['oc']
        for opt in ['server', 'certificate_authority', 'token']:
            if opt in connection:
                self.oc_cmd += ['--' + opt.replace('_', '-') + '=' + connection[opt]]
        if 'insecure_skip_tls_verify' in connection:
            if type(connection['insecure_skip_tls_verify']) == types.BooleanType:
                self.oc_cmd += ['--insecure-skip-tls-verify']
            elif connection['insecure_skip_tls_verify']:
                self.oc_cmd += ['--insecure-skip-tls-verify='+connection['insecure_skip_tls_verify']]
        for arg in self.oc_cmd:
            if arg.startswith('--token='):
                module.no_log_values.add(arg[8:])

    def run_oc(self, args, **kwargs):
        if self.module._verbosity < 3:
            # Not running in debug mode, call module run_command which filters passwords
            return self.module.run_command(self.oc_cmd + args, **kwargs)

        check_rc = True
        if 'check_rc' in kwargs:
            check_rc = kwargs['check_rc']
        kwargs['check_rc'] = False

        (rc, stdout, stderr) = self.module.run_command(self.oc_cmd + args, **kwargs)

        if rc != 0 and check_rc:
            self.module.fail_json(cmd=args, rc=rc, stdout=stdout, stderr=stderr, msg=stderr)

        return (rc, stdout, stderr)

    def get_current_resource(self):
        command = ['get', self.resource['kind'], self.resource['metadata']['name'], '-o', 'json']
        if self.namespace:
            command += ['-n', self.namespace]
        (rc, stdout, stderr) = self.run_oc(command, check_rc=False)
        if rc != 0:
            return None
        resource = json.loads(stdout)
        if self.namespace:
            resource['metadata']['namespace'] = self.namespace
        return resource

    def normalize_resource(self, resource):
        """
        Given an OpenShift resource definition, return a modified version
        suitable for comparison by removing autogenerated fields and setting
        defaults. The original resource is not modified.

        The implemented behavior here is mostly detective work and may miss
        any number of cases. If this code is in error it should result only
        in indicating that resources are different when they are not
        meaningfully different.
        """
        # There is a lot of configuration here in this code. I wish I could
        # externalize it somehow, but when this module runs only this file
        # is copied to the remote. I haven't yet figured out a good way to
        # put this in an external file and get that file to the remote
        # system without making this more complex than it already is.

        # The filter variable is built up to mask out any autogenerated fields.
        # Lists should be a single value and are used to override every item in
        # corresponding list in the resource
        resource = copy.deepcopy(resource)
        self.normalize_override_dynamic_config(resource)
        normalize_resource_method_name = 'normalize_resource_' + resource['kind']
        normalize_resource_method = None
        try:
            normalize_resource_method = getattr(self, normalize_resource_method_name)
        except AttributeError:
            pass
        if normalize_resource_method:
            normalize_resource_method(resource)
        return resource

    def normalize_override_dynamic_config(self, resource):
        # Override common dynamic metadata
        merge_dict(
            resource,
            {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/last-applied-configuration": ""
                    },
                    "creationTimestamp": "",
                    "generation": 0,
                    "namespace": "",
                    "resourceVersion": 0,
                    "selfLink": "",
                    "uid": ""
                }
            },
            overwrite=True
        )
        # If the resource has a template, then also override template metadata
        spec_template = resource.get('spec', {}).get('template', None)
        if spec_template:
            merge_dict(
                resource['spec'],
                {
                    "template": {
                        "metadata": {
                            "creationTimestamp": ""
                        }
                    },
                    "templateGeneration": 0
                },
                overwrite=True
            )

    def normalize_resource_BuildConfig(self, resource):
        normalize_BuildConfig_V1(resource)

    def normalize_resource_ClusterResourceQuota(self, resource):
        normalize_ClusterResourceQuota_V1(resource)

    def normalize_resource_ClusterRole(self, resource):
        normalize_ClusterRole_V1(resource)

    def normalize_resource_ClusterRoleBinding(self, resource):
        normalize_ClusterRoleBinding_V1(resource)

    def normalize_resource_CronJob(self, resource):
        normalize_CronJob_V1beta1(resource)

    def normalize_resource_DaemonSet(self, resource):
        normalize_DaemonSet_V1(resource)

    def normalize_resource_Deployment(self, resource):
        normalize_Deployment_V1(resource)

    def normalize_resource_DeploymentConfig(self, resource):
        # Before we can normalize the Deploymentconfig triggers we need to set
        # the namespace on any image change triggers...
        for trigger in resource['spec'].get('triggers', []):
            if 'imageChangeParams' in trigger:
                set_dict_defaults(trigger['imageChangeParams']['from'], {
                    'namespace': self.namespace
                })
        normalize_DeploymentConfig_V1(resource)

    def normalize_resource_HorizontalPodAutoscaler(self, resource):
        normalize_HorizontalPodAutoscaler(resource)

    def normalize_resource_ImageStream(self, resource):
        normalize_ImageStream_V1(resource)

    def normalize_resource_LimitRange(self, resource):
        normalize_LimitRange_V1(resource)

    def normalize_resource_NetworkPolicy(self, resource):
        normalize_NetworkPolicy_V1(resource)

    def normalize_resource_PersistentVolume(self, resource):
        normalize_PersistentVolume_V1(resource)

    def normalize_resource_PersistentVolumeClaim(self, resource):
        normalize_PersistentVolumeClaim_V1(resource)

    def normalize_resource_Project(self, resource):
        normalize_Project_V1(resource)

    def normalize_resource_ResourceQuota(self, resource):
        normalize_ResourceQuota_V1(resource)

    def normalize_resource_Role(self, resource):
        normalize_Role_V1(resource)

    def normalize_resource_RoleBinding(self, resource):
        normalize_RoleBinding_V1(resource)

    def normalize_resource_Route(self, resource):
        normalize_Route_V1(resource)

    def normalize_resource_SecurityContextConstraints(self, resource):
        normalize_SecurityContextConstraints_V1(resource)

    def normalize_resource_Service(self, resource):
        normalize_Service_V1(resource)

    def normalize_resource_StatefulSet(self, resource):
        normalize_StatefulSet_V1(resource)

    def comparison_fields(self):
        if self.resource['kind'] in ['ClusterRole', 'Role']:
          return ['metadata', 'rules']
        elif self.resource['kind'] in ['ClusterRoleBinding', 'RoleBinding']:
          return ['metadata', 'roleRef', 'subjects']
        elif self.resource['kind'] in ['ConfigMap', 'Secret']:
          return ['metadata', 'data']
        elif self.resource['kind'] == 'Group':
          return ['metadata', 'users']
        elif self.resource['kind'] == 'Project':
          return ['metadata', 'labels']
        elif self.resource['kind'] == 'ServiceAccount':
          return ['metadata', 'imagePullSecrets', 'secrets']
        elif self.resource['kind'] == 'Template':
          return ['metadata', 'labels', 'objects', 'parameters']
        elif self.resource['kind'] == 'SecurityContextConstraints':
          return self.resource.keys()
        elif self.resource['kind'] == 'ValidatingWebhookConfiguration':
          return ['metadata','webhooks']
        elif self.resource['kind'] == 'MutatingWebhookConfiguration':
          return ['metadata','webhooks']
        else:
          return ['metadata', 'spec']

    def compare_resource(self, resource, compare_to=None):
        if compare_to == None:
            compare_to = self.resource

        config = self.normalize_resource(compare_to)
        current = self.normalize_resource(resource)
        patch = []
        for field in self.comparison_fields():
            if field in current and not field in config:
                patch.extend([{
                    "op": "test",
                    "path": "/" + field,
                    "value": current[field]
                }, {
                    "op": "remove",
                    "path": "/" + field
                }])
            elif field in config and not field in current:
                patch.append({
                    "op": "add",
                    "path": "/" + field,
                    "value": config[field]
                })
            elif field in config and field in current \
            and config[field] != current[field]:
                patch.extend(
                    make_field_patch(field, current[field], config[field])
                )
        return patch

    def check_patch(self, resource):
        '''return differences created by applying patch'''
        if resource == None:
            raise Exception("Cannot patch %s %s, resource not found" % (
                self.resource['kind'], self.resource['metadata']['name']
            ))

        # Remove namespace from metadata
        resource['metadata']['namespace'] = ''

        # Create tempfile for local changes
        temp_fd, temp_path = tempfile.mkstemp(suffix='.json')

        # Write json to tempfile
        with os.fdopen(temp_fd, 'w') as f:
            f.write(json.dumps(resource))

        command = ['patch', '--local', '--output=json',
            '--filename=' + temp_path,
            '--patch=' + json.dumps(self.resource),
            '--type=' + self.patch_type
        ]
        rc, stdout, stderr = self.run_oc(command, check_rc=True)
        return self.compare_resource(resource, json.loads(stdout))

    def set_dynamic_values(self, current_resource):
        """
        Dynamic values must be set in the resource to be compatible with apply
        action. If the last-applied-configuration annotation has an value set
        that is not in the applied configuration then this is interpreted as an
        attempt to remove the dynamic value.
        """
        if self.resource['kind'] == 'PersistentVolumeClaim':
            current_spec = current_resource.get('spec', {})
            resource_spec = self.resource['spec']
            if 'storageClassName' not in resource_spec and 'storageClassName' in current_spec:
                resource_spec['storageClassName'] = current_spec['storageClassName']
            if 'volumeName' not in resource_spec and 'volumeName' in current_spec:
                resource_spec['volumeName'] = current_spec['volumeName']

        elif self.resource['kind'] == 'Service':
            current_spec = current_resource.get('spec', {})
            resource_spec = self.resource['spec']
            if 'clusterIP' not in resource_spec and 'clusterIP' in current_spec:
                resource_spec['clusterIP'] = current_spec['clusterIP']

        elif self.resource['kind'] == 'ServiceAccount':
            if 'imagePullSecrets' not in self.resource:
                self.resource['imagePullSecrets'] = []
            for secret in current_resource['imagePullSecrets']:
                if '-dockercfg-' == secret['name'][-16:-5]:
                    self.resource['imagePullSecrets'].append(copy.deepcopy(secret))
            if 'secrets' not in self.resource:
                self.resource['secrets'] = []
            for secret in current_resource['secrets']:
                if '-dockercfg-' == secret['name'][-16:-5] \
                or '-token-' == secret['name'][-12:-5]:
                    self.resource['secrets'].append(copy.deepcopy(secret))

    def get_resource_version_and_last_applied_configuration(self, resource):
        if not resource:
            return None, None

        metadata = resource.get('metadata', {})
        resource_version = metadata \
            .pop('resourceVersion', None)
        last_applied_configuration = metadata \
            .get('annotations', {}) \
            .pop('kubectl.kubernetes.io/last-applied-configuration', None)
        return resource_version, last_applied_configuration

    # def set_resource_version_and_last_applied_configuration(self, resource_version, last_applied_configuration):
    #     if not resource_version or not last_applied_configuration:
    #         return
    #     merge_dict(self.resource, {
    #         'metadata': {
    #             'annotations': {
    #                 'kubectl.kubernetes.io/last-applied-configuration': last_applied_configuration
    #             },
    #             'resourceVersion': resource_version
    #         }
    #     }, overwrite=True)

    def provision(self):
        current_resource = self.get_current_resource()
        current_resource_version, current_last_applied_configuration = \
            self.get_resource_version_and_last_applied_configuration(current_resource)
        if current_resource and self.action in ['apply', 'replace']:
            self.set_dynamic_values(current_resource)

        # Check if changes are required and if we need to reset the apply metadata.
        reset_last_applied_configuration = False
        patch = None
        if self.action == 'create':
            if current_resource:
                self.resource = current_resource
                if not self.generate_resources:
                    return
        elif self.action == 'apply':
            if current_resource != None:
                patch = self.compare_resource(current_resource)
                if not patch:
                    self.resource = current_resource
                    if not self.generate_resources:
                        return
                # If current resource does not match last_applied_configuration
                # then we must switch to replace mode or risk unexpected behavior
                if(current_resource_version
                and current_last_applied_configuration
                and not self.compare_resource(
                    current_resource, json.loads(current_last_applied_configuration)
                )):
                    self.action = 'replace'
                    reset_last_applied_configuration = True
        elif self.action == 'patch':
            patch = self.check_patch(current_resource)
            if not patch:
                self.resource = current_resource
                if not self.generate_resources:
                    return
        elif self.action == 'replace':
            if current_resource == None:
                self.action = 'create'
            else:
                patch = self.compare_resource(current_resource)
                if not patch:
                    self.resource = current_resource
                    if not self.generate_resources:
                        return
        elif self.action == 'delete':
            if current_resource == None:
                if not self.generate_resources:
                    return
        elif self.action == 'ignore':
            return

        if self.fail_on_change:
            raise Exception(json.dumps(patch))

        # Record calculated differences expressed as a json patch
        self.patch = patch

        # Handle check mode by returning without performing action
        self.changed = True
        if self.module.check_mode:
            return

        if self.generate_resources:
            if not self.namespace:
                scope = "cluster"
            else:
                scope = self.namespace

            if not os.path.exists('./manifests'):
                os.mkdir('./manifests')

            resource_filename = "%s_%s_%s.json" % (scope, self.resource['kind'], self.resource['metadata']['name'])
            resource_file = open("./manifests/" + resource_filename, 'w')
            resource_file.write(str(json.dumps(self.resource)))
            resource_file.close()
            return

        # Perform action on resource
        if self.action == 'patch':
            command = [self.action,
                    '-f',
                    '-',
                    '--patch=' + json.dumps(self.resource),
                    '--type=' + self.patch_type
            ]
            if self.namespace:
                command += ['-n', self.namespace]
            self.run_oc(command, data=json.dumps(self.resource), check_rc=True)
        else: # apply, create, delete, replace
            resource = copy.deepcopy(self.resource)
            if self.action == 'apply':
                merge_dict(resource, {
                    'metadata': {
                        'annotations': {
                            'kubectl.kubernetes.io/last-applied-configuration': current_last_applied_configuration
                        },
                        'resourceVersion': current_resource_version
                    }
                })
            command = [self.action, '-f', '-']
            if self.namespace:
                command += ['-n', self.namespace]
            if reset_last_applied_configuration:
                command += ['--save-config']
            self.run_oc(command, data=json.dumps(resource), check_rc=True)

def run_module():
    module_args = {
        'action': {
            'type': 'str',
            'required': False,
            'default': 'apply'
        },
        'patch_type': {
            'type': 'str',
            'required': False,
            'default': 'strategic'
        },
        'namespace': {
            'type': 'str',
            'required': False,
        },
        'connection': {
            'type': 'dict',
            'required': False,
            'default': {}
        },
        'resource': {
            'type': 'dict',
            'required': True
        },
        # Useful when testing...
        'fail_on_change': {
            'type': 'bool',
            'default': False
        },
        # Use role as resource generator instead of provisioner
        'generate_resources': {
            'type': 'bool',
            'required': False,
            'default': False
        }
    }

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    provisioner = OpenShiftProvision(module)

    try:
        provisioner.provision()
    except Exception as e:
        module.fail_json(
            msg=str(e),
            action=provisioner.action,
            traceback=traceback.format_exc().split('\n'),
            resource=provisioner.resource
        )

    module.exit_json(
        action=provisioner.action,
        changed=provisioner.changed,
        patch=provisioner.patch,
        resource=provisioner.resource
    )

def main():
    run_module()

if __name__ == "__main__":
    main()
