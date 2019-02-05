#!/usr/bin/python

import copy
import json
import os
import re
import tempfile
import traceback
import types

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
resource:
  description: Resource definition
  type: dict
'''

from ansible.module_utils.basic import AnsibleModule

def make_field_patch(field, current, config):
    # Adapted from jsonpatch to add current value
    def compare_values(path, value, other):
        if value == other:
            return
        if isinstance(value, dict) and isinstance(other, dict):
            for operation in compare_dict(path, value, other):
                yield operation
        elif isinstance(value, list) and isinstance(other, list):
            for operation in compare_list(path, value, other):
                yield operation
        else:
            yield {'op': 'test', 'path': '/'.join(path), 'value': value}
            yield {'op': 'replace', 'path': '/'.join(path), 'value': other}

    def compare_dict(path, src, dst):
        for key in src:
            if key not in dst:
                yield {'op': 'test', 'path': '/'.join(path + [key]), 'value': src[key]}
                yield {'op': 'remove', 'path': '/'.join(path + [key])}
                continue
            current = path + [key]
            for operation in compare_values(current, src[key], dst[key]):
                yield operation
        for key in dst:
            if key not in src:
                yield {'op': 'add', 'path': '/'.join(path + [key]), 'value': dst[key]}

    def compare_list(path, src, dst):
        lsrc, ldst = len(src), len(dst)
        for idx in range(min(lsrc, ldst)):
            current = path + [str(idx)]
            for operation in compare_values(current, src[idx], dst[idx]):
                yield operation
        if lsrc < ldst:
            for idx in range(lsrc, ldst):
                current = path + [str(idx)]
                yield {'op': 'add', 'path': '/'.join(current), 'value': dst[idx]}
        elif lsrc > ldst:
            for idx in reversed(range(ldst, lsrc)):
                yield {'op': 'test', 'path': '/'.join(path + [str(idx)]), 'value': src[idx]}
                yield {'op': 'remove', 'path': '/'.join(path + [str(idx)])}

    return list(compare_values(['/' + field], current, config))

def sort_lists_in_dict(d):
    """Given a dictionary where some values are lists, sort those lists"""
    for k, v in d.items():
        if type(v) is list:
            d[k] = sorted(set(v))

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
    elif memory[-1:] in ['k','K']:
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

def normalize_container_resources(resources):
    if not resources:
        return {}
    if 'limits' in resources:
        resources['limits'] = normalize_resource_units(resources['limits'])
    if 'requests' in resources:
        resources['requests'] = normalize_resource_units(resources['requests'])
    return resources

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

def merge_dict_list(merged_list, patch, overwrite=True):
    """
    Given a list of dictionaries and a patch, call merge_dict for each
    dictionary in the list.
    """
    if not merged_list:
        return []
    if not type(merged_list) is list:
        raise Exception(
            "Unable to merge {} with list".format(
                type(merged_list).__name__
            )
        )
    for entry in merged_list:
        if type(entry) is dict:
            merge_dict(entry, patch, overwrite=overwrite)
        else:
            raise Exception(
                "Unable to merge item {} with dict".format(
                    type(entry).__name__
                )
            )
    #merged_list.sort(key=str)
    return merged_list

def normalize_env_list(env_list):
    if env_list == None:
        return []
    for env in env_list:
        # Openshift drops the empty value strings, put those back to compare
        if 'value' not in env:
            env['value'] = ''
    env_list.sort(key=lambda e: e['name'])
    return env_list

def port_list_defaults(items):
    return merge_dict_list(
        items,
        { "protocol": "TCP" },
        overwrite=False
    )

def imagestream_tags_defaults(tags):
    return merge_dict_list(
        tags,
        {
            "referencePolicy": {
                "type": "Source"
            }
        },
        overwrite=False
    )

def pod_volumes_defaults(volumes):
    if not volumes:
        return []
    for volume in volumes:
        if 'configMap' in volume:
            if 'defaultMode' not in volume['configMap']:
                volume['configMap']['defaultMode'] = 0o644
        elif 'hostPath' in volume:
            if 'type' not in volume['hostPath']:
                volume['hostPath']['type'] = ''
        elif 'secret' in volume:
            if 'defaultMode' not in volume['secret']:
                volume['secret']['defaultMode'] = 0o644
    return volumes

def pod_template_defaults(pod_template):
    merge_dict(pod_template, {
        "metadata": {
            "creationTimestamp": None,
        },
        "spec": {
            "containers": lambda containers : merge_dict_list(
                containers,
                {
                    "env": normalize_env_list,
                    "imagePullPolicy": "IfNotPresent",
                    "livenessProbe": {
                        "httpGet": {
                            "scheme": "HTTP"
                        },
                        "initialDelaySeconds": 30,
                        "periodSeconds": 10,
                        "successThreshold": 1,
                        "failureThreshold": 3
                    },
                    "ports": port_list_defaults,
                    "readinessProbe": {
                        "httpGet": {
                            "scheme": "HTTP"
                        },
                        "initialDelaySeconds": 30,
                        "periodSeconds": 10,
                        "successThreshold": 1,
                        "failureThreshold": 3
                    },
                    "resources": normalize_container_resources,
                    "terminationMessagePath": "/dev/termination-log",
                    "terminationMessagePolicy": "File",
                    "volumeMounts": []
                },
                overwrite=False
            ),
            "dnsPolicy": "ClusterFirst",
            "restartPolicy": "Always",
            "securityContext": {},
            "schedulerName": "default-scheduler",
            "terminationGracePeriodSeconds": 30,
            "volumes": pod_volumes_defaults
        }
    }, overwrite=False)

    # If pod template uses hostNetwork then ports on containers have
    # hostPort which defaults to containerPort
    if pod_template['spec'].get('hostNetwork', False):
        for container in pod_template['spec']['containers']:
            for port in container['ports']:
                if 'hostPort' not in port:
                    port['hostPort'] = port['containerPort']
    return pod_template


class OpenShiftProvision:
    def __init__(self, module):
        self.module = module
        self.changed = False
        self.action = module.params['action']
        self.fail_on_change = module.params['fail_on_change']
        self.patch = None
        self.patch_type = module.params['patch_type']
        self.resource = module.params['resource']

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

        connection = module.params['connection']
        if 'oc_cmd' in connection:
            self.oc_cmd = connection['oc_cmd'].split()
        else:
            self.oc_cmd = ['oc']
        for opt in ['server','certificate_authority','token']:
            if opt in connection:
                self.oc_cmd += ['--' + opt.replace('_', '-') + '=' + connection[opt]]
        if 'insecure_skip_tls_verify' in connection:
            if type(connection['insecure_skip_tls_verify']) == types.BooleanType:
                self.oc_cmd += ['--insecure-skip-tls-verify']
            elif connection['insecure_skip_tls_verify']:
                self.oc_cmd += ['--insecure-skip-tls-verify='+connection['insecure_skip_tls_verify']]

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
        merge_dict(
            resource,
            {
                "metadata": {
                    "annotations": {
                        "template.alpha.openshift.io/wait-for-ready": "true"
                    }
                },
                "spec": {
                    "nodeSelector": None,
                    "resources": {},
                    "runPolicy": "Serial",
                    "source": {
                        "contextDir": "",
                        "git": {
                            "ref": ""
                        }
                    },
                    "strategy": {
                        "sourceStrategy": {
                            "env": normalize_env_list,
                            "from": {
                                "namespace": ""
                            }
                        }
                    },
                    # Build config default imageChange trigger
                    "triggers": [{
                        "imageChange": {}
                    }]
                }
            },
            overwrite=False
        )


    def normalize_resource_ClusterRole(self, resource):
        for rule in resource.get('rules',[]):
            sort_lists_in_dict(rule)

    def normalize_resource_CronJob(self, resource):
        merge_dict(
            resource,
            {
                "spec": {
                    "jobTemplate": {
                        "metadata": {
                            "creationTimestamp": None
                        },
                        "spec": {
                            "template": pod_template_defaults
                        }
                    }
                }
            },
            overwrite=False
        )

    def normalize_resource_DaemonSet(self, resource):
        merge_dict(
            resource,
            {
                "spec": {
                    "revisionHistoryLimit": 10,
                    "template": pod_template_defaults
                }
            },
            overwrite=False
        )

    def normalize_resource_Deployment(self, resource):
        resource["metadata"]["annotations"]["deployment.kubernetes.io/revision"] = 0
        merge_dict(
            resource,
            {
                "spec": {
                    "progressDeadlineSeconds": 600,
                    "revisionHistoryLimit": 10,
                    "template": pod_template_defaults
                }
            },
            overwrite=False
        )

    def normalize_resource_DeploymentConfig(self, resource):
        merge_dict(
            resource,
            {
                "spec": {
                    "revisionHistoryLimit": 10,
                    "strategy": {
                        "activeDeadlineSeconds": 21600,
                        "recreateParams": {
                            "timeoutSeconds": 600
                        },
                        "resources": {}
                    },
                    "template": pod_template_defaults,
                    "test": False,
                    "triggers": lambda triggers : self.deploymentconfig_trigger_defaults(triggers)
                }
            },
            overwrite=False
        )
        # FIXME - Only clear image field in containers referenced by image change triggers
        has_image_change_trigger = False
        for trigger in resource['spec']['triggers']:
            if trigger['type'] == 'ImageChange':
                has_image_change_trigger = True
        for container in resource['spec']['template']['spec']['containers']:
            if has_image_change_trigger:
                container['image'] = ''

    def normalize_resource_HorizontalPodAutoscaler(self, resource):
        resource["metadata"]["annotations"]["autoscaling.alpha.kubernetes.io/conditions"] = ""

    def normalize_resource_ImageStream(self, resource):
        merge_dict(
            resource,
            {
                "metadata": {
                    "annotations": {
                        "openshift.io/image.dockerRepositoryCheck": ""
                    }
                },
                "spec": {
                    "tags": lambda tags : merge_dict_list(
                        tags,
                        {
                            "generation": 0
                        },
                        overwrite=True
                    )
                }
            },
            overwrite=True
        )
        merge_dict(
            resource,
            {
                "spec": {
                    "dockerImageRepository": '',
                    "lookupPolicy": {
                        "local": False
                    },
                    "tags": imagestream_tags_defaults
                }
            },
            overwrite=False
        )

    def normalize_resource_NetworkPolicy(self, resource):
        merge_dict(
            resource,
            {
                "spec": {
                    "policyTypes": [ "Ingress" ],
                    "podSelector": {}
                }
            },
            overwrite=False
        )

    def normalize_resource_PersistentVolume(self, resource):
        merge_dict(
            resource,
            {
                "metadata": {
                    "finalizers": [
                        "kubernetes.io/pv-protection"
                    ]
                },
                "spec": {
                    "persistentVolumeReclaimPolicy": "Retain"
                }
            },
            overwrite=False
        )
        resource["metadata"]["annotations"]["pv.kubernetes.io/bound-by-controller"] = ""
        resource["spec"]["claimRef"] = ""

    def normalize_resource_PersistentVolumeClaim(self, resource):
        merge_dict(
            resource,
            {
                "metadata": {
                    "finalizers": [
                        "kubernetes.io/pvc-protection"
                    ]
                },
                "spec": {}
            },
            overwrite=False
        )
        resource["metadata"]["annotations"]["pv.kubernetes.io/bind-completed"] = ""
        resource["metadata"]["annotations"]["pv.kubernetes.io/bound-by-controller"] = ""
        resource["metadata"]["annotations"]["volume.beta.kubernetes.io/storage-provisioner"] = ""
        resource["spec"]["volumeName"] = ""

    def normalize_resource_Role(self, resource):
        for rule in resource.get('rules',[]):
            sort_lists_in_dict(rule)

    def normalize_resource_Route(self, resource):
        merge_dict(
            resource,
            {
                "metadata": {
                    "annotations": {
                        "openshift.io/host.generated": "false"
                    }
                },
                "spec": {
                    "host": '',
                    "to": {
                        "weight": 100
                    },
                    "wildcardPolicy": "None"
                }
            },
            overwrite=False
        )
        # If route host is generated, then need to blank out the host field to compare
        if resource['spec']['host'] == '':
            resource['metadata']['annotations']['openshift.io/host.generated'] = 'true'
        if resource['metadata']['annotations']['openshift.io/host.generated'] == 'true':
            resource['spec']['host'] = ''

    def normalize_resource_SecurityContextConstraints(self, resource):
        # Sometimes SecurityContextConstraints come back with values of None
        # rather than an empty list.
        if resource.get('groups', None) == None:
            resource['groups'] = []
        if resource.get('users', None) == None:
            resource['users'] = []
        # List order in SCC are arbitrary
        sort_lists_in_dict(resource)

    def normalize_resource_Service(self, resource):
        merge_dict(
            resource,
            {
                "spec": {
                    "ports": port_list_defaults,
                    "sessionAffinity": "None",
                    "sessionAffinityConfig": {
                        "clientIP": {
                            "timeoutSeconds": 10800
                        }
                    },
                    "type": "ClusterIP"
                }
            },
            overwrite=False
        )
        if 'service.alpha.openshift.io/serving-cert-secret-name' in resource['metadata']['annotations']:
            resource["metadata"]["annotations"]["service.alpha.openshift.io/serving-cert-signed-by"] = ""

    def normalize_resource_StatefulSet(self, resource):
        merge_dict(
            resource,
            {
                "spec": {
                    "replicas": 1,
                    "revisionHistoryLimit": 10,
                    "template": pod_template_defaults,
                    "volumeClaimTemplates": []
                }
            },
            overwrite=False
        )
        merge_dict_list(
            resource['spec']['volumeClaimTemplates'],
            {
                "metadata": {
                    "creationTimestamp": ""
                },
                "status": ""
            },
            overwrite=True
        )

    # Needs to know the current namespace...
    def deploymentconfig_trigger_defaults(self, triggers):
        if not triggers:
            return [ { "type": "ConfigChange" } ]
        if not type(triggers) is list:
            raise Exception("DeploymentConfig triggers must be a list")
        for trigger in triggers:
            if not type(trigger) is dict:
                raise Exception("DeploymentConfig triggers must only include dict")
            if 'type' not in trigger:
                raise Exception("DeploymentConfig triggers must specify type")
            if trigger['type'] == 'ImageChange':
                merge_dict(
                    trigger,
                    {
                        "imageChangeParams": {
                            "from": {
                                "namespace": self.namespace
                            }
                        }
                    },
                    overwrite=False
                )
                trigger['imageChangeParams']['lastTriggeredImage'] = ''
        return triggers


    def comparison_fields(self):
        if self.resource['kind'] == 'ClusterRole':
          return ['metadata', 'rules']
        elif self.resource['kind'] in ['ConfigMap', 'Secret']:
          return ['metadata', 'data']
        elif self.resource['kind'] == 'Group':
          return ['metadata', 'users']
        elif self.resource['kind'] == 'ServiceAccount':
          return ['metadata', 'imagePullSecrets', 'secrets']
        elif self.resource['kind'] == 'Template':
          return ['metadata', 'labels', 'objects', 'parameters']
        elif self.resource['kind'] == 'SecurityContextConstraints':
          return self.resource.keys()
        else:
          return ['metadata', 'spec']


    def compare_resource(self, resource, compare_to=None):
        if compare_to == None:
            compare_to = self.resource

        current = self.normalize_resource(compare_to)
        config = self.normalize_resource(resource)
        patch = []
        for field in self.comparison_fields():
            if field in current and not field in config:
                patch.extend([{
                    "op": "test",
                    "path": "/" + field,
                    "value": current[field]
                },{
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
        '''return true if patch would not change resource'''
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
        return resource == json.loads(stdout)


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

        metadata = resource.get('metadata',{})
        resource_version = metadata \
            .get('resourceVersion', None)
        last_applied_configuration = metadata \
            .get('annotations', {}) \
            .get('kubectl.kubernetes.io/last-applied-configuration', None)
        return resource_version, last_applied_configuration

    def set_resource_version_and_last_applied_configuration(self, resource_version, last_applied_configuration):
        if not resource_version or not last_applied_configuration:
            return
        merge_dict(self.resource, {
            'metadata': {
                'annotations': {
                    'kubectl.kubernetes.io/last-applied-configuration': last_applied_configuration
                },
                'resourceVersion': resource_version
            }
        }, overwrite=True)

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
                return
        elif self.action == 'apply':
            if current_resource != None:
                patch = self.compare_resource(current_resource)
                if not patch:
                    self.resource = current_resource
                    return
                # If current resource does not match last_applied_configuration
                # then we must switch to replace mode or risk unexpected behavior
                if( current_resource_version
                and current_last_applied_configuration
                and not self.compare_resource(
                    current_resource, json.loads(current_last_applied_configuration)
                )):
                    self.action = 'replace'
                    reset_last_applied_configuration = True
        elif self.action == 'patch':
            if self.check_patch(current_resource):
                self.resource = current_resource
                return
        elif self.action == 'replace':
            if current_resource == None:
                self.action = 'create'
            else:
                patch = self.compare_resource(current_resource)
                if not patch:
                    self.resource = current_resource
                    return
        elif self.action == 'delete':
            if current_resource == None:
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

        # Perform action on resource
        if self.action == 'delete':
            command = ['delete', self.resource['kind'], self.resource['metadata']['name']]
            if self.namespace:
                command += ['-n', self.namespace]
            (rc, stdout, stderr) = self.run_oc(command, check_rc=True)
        elif self.action == 'patch':
            command = ['patch', self.resource['kind'], self.resource['metadata']['name'],
                '--patch=' + json.dumps(self.resource),
                '--type=' + self.patch_type
            ]
            if self.namespace:
                command += ['-n', self.namespace]
            self.run_oc(command, check_rc=True)
        else: # apply, create, replace
            if self.action == 'apply':
                self.set_resource_version_and_last_applied_configuration(
                    current_resource_version,
                    current_last_applied_configuration
                )
            command = [self.action, '-f', '-']
            if self.namespace:
                command += ['-n', self.namespace]
            if reset_last_applied_configuration:
                command += ['--save-config']
            self.run_oc(command, data=json.dumps(self.resource), check_rc=True)

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
            action = provisioner.action,
            traceback=traceback.format_exc().split('\n'),
            resource=provisioner.resource
        )

    module.exit_json(
        action = provisioner.action,
        changed = provisioner.changed,
        patch = provisioner.patch,
        resource = provisioner.resource
    )

def main():
    run_module()

if __name__ == "__main__":
    main()
