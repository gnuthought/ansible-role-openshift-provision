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
  resource:
    description:
    - Resource definition
    required: true
    default: None
    aliases: []
  namespace:
    description:
    - Namespace in which to provision resource
    required: false
    aliases: []
  action:
    description:
    - Action to perform on resource: apply, create, delete, patch, replace
    default: apply
    required: false
    aliases: []
  patch_type:
    description:
    - Type of patch to use with patch action
    default: strategic
    required: false
    aliases: []
  connection:
    description:
    - Dictionary of connection options, may include 'token', 'server', 'certificate_authority', 'insecure_skip_tls_verify', and 'oc_cmd'
    default: {}
    required: false
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

class OpenShiftProvision:
    def __init__(self, module):
        self.module = module
        self.changed = False
        self.action = module.params['action']
        self.fail_on_change = module.params['fail_on_change']
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

    def merge_dict(self, merged, patch, overwrite=True):
        for k, v in patch.items():
            if type(v) is dict:
                if not k in merged:
                    merged[k] = copy.deepcopy(v)
                elif type(merged[k]) is dict:
                    self.merge_dict(merged[k], v, overwrite)
                else:
                    raise Exception("Unable to merge " + type(merged[key]).__name__ + " with dict")
            elif callable(v):
                merged[k] = v(merged[k] if k in merged else None)
            elif not k in merged:
                merged[k] = copy.deepcopy(v)
            elif overwrite:
                merged[k] = copy.deepcopy(v)

    def merge_dict_list(self, merged, patch, overwrite=True):
        if not merged:
            return []
        if not type(merged) is list:
            raise Exception(
                "Unable to merge {} with list".format(
                    type(merged).__name__
                )
            )
        for entry in merged:
            if type(entry) is dict:
                self.merge_dict(entry, patch, overwrite=overwrite)
            else:
                raise Exception(
                    "Unable to merge item {} with dict".format(
                        type(entry).__name__
                    )
                )
        merged.sort(key=str)
        return merged

    def merge(self, source, patch):
        merged = copy.deepcopy(source)
        self.merge_dict(merged, patch)
        return merged

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
        if self.resource['kind'] in [
            'DaemonSet', 'Deployment', 'HorizontalPodAutoscaler', 'ImageStream', 'ReplicaSet', 'StatefulSet', 'StorageClass'
        ]:
            command = ['get']
        else:
            command = ['export']
        command += [self.resource['kind'], self.resource['metadata']['name'], '-o', 'json']
        if self.namespace:
            command += ['-n', self.namespace]
        (rc, stdout, stderr) = self.run_oc(command, check_rc=False)
        if rc != 0:
            return None
        resource = json.loads(stdout)
        if self.namespace:
            resource['metadata']['namespace'] = self.namespace
        return resource

    def filter_differences(self, resource):
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
        override = {
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
        }

        if resource['kind'] in ['DaemonSet', 'Deployment', 'DeploymentConfig', 'ReplicationController', 'ReplicaSet', 'StatefulSet']:
            override["spec"] = {
                "template": {
                    "metadata": {
                        "creationTimestamp": ""
                    }
                },
                "templateGeneration": 0
            }
        if resource['kind'] == 'StatefulSet':
            override["spec"]["volumeClaimTemplates"] = lambda items : self.merge_dict_list(
                items,
                {
                    "metadata": {
                        "creationTimestamp": ""
                    },
                    "status": ""
                },
                overwrite=True
            )
        elif resource['kind'] == 'Deployment':
            override["metadata"]["annotations"]["deployment.kubernetes.io/revision"] = 0
        elif resource['kind'] == 'HorizontalPodAutoscaler':
            override["metadata"]["annotations"]["autoscaling.alpha.kubernetes.io/conditions"] = ""
        elif resource['kind'] == 'ImageStream':
            override["metadata"]["annotations"]["openshift.io/image.dockerRepositoryCheck"] = ""
            override["spec"] = {
                "tags": lambda tags : self.merge_dict_list(
                    tags,
                    {
                        "generation": 0
                    },
                    overwrite=True
                )
            }
        elif resource['kind'] == 'PersistentVolume':
            override["metadata"]["annotations"]["pv.kubernetes.io/bound-by-controller"] = ""
            override["spec"] = {
                "claimRef": ""
            }
        elif resource['kind'] == 'PersistentVolumeClaim':
            override["spec"] = {
                "volumeName": ""
            }
            override["metadata"]["annotations"]["pv.kubernetes.io/bind-completed"] = ""
            override["metadata"]["annotations"]["pv.kubernetes.io/bound-by-controller"] = ""
            override["metadata"]["annotations"]["volume.beta.kubernetes.io/storage-provisioner"] = ""
            # If storageClassName is not given, then it may be dynamically assigned
            if "storageClassName" not in self.resource["spec"]:
                override["spec"]["storageClassName"] = ""

        # Copy and override
        ret = self.merge(resource, override)

        # Now we set defaults and handle special cases
        if ret['kind'] == 'BuildConfig':
            self.merge_dict(ret, {
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
                            "env": lambda env : self.empty_value_defaults(env),
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
            }, overwrite=False)
        elif ret['kind'] == 'DaemonSet':
            self.merge_dict(ret, {
                "spec": {
                    "template": lambda pod_template : self.pod_template_defaults(pod_template),
                }
            }, overwrite=False)
        elif ret['kind'] == 'DeploymentConfig':
            self.merge_dict(ret, {
                "spec": {
                    "strategy": {
                        "activeDeadlineSeconds": 21600,
                        "recreateParams": {
                            "timeoutSeconds": 600
                        },
                        "resources": {}
                    },
                    "template": lambda pod_template : self.pod_template_defaults(pod_template),
                    "test": False,
                    "triggers": lambda triggers : self.deploymentconfig_trigger_defaults(triggers)
                }
            }, overwrite=False)
            has_image_change_trigger = False
            for trigger in ret['spec']['triggers']:
                if trigger['type'] == 'ImageChange':
                    has_image_change_trigger = True
            for container in ret['spec']['template']['spec']['containers']:
                if has_image_change_trigger:
                    container['image'] = ''
        elif ret['kind'] == 'ImageStream':
            self.merge_dict(ret, {
                "spec": {
                    "dockerImageRepository": '',
                    "lookupPolicy": {
                        "local": False
                    },
                    "tags": lambda tags : self.imagestream_tags_defaults(tags)
                }
            }, overwrite=False)
        elif ret['kind'] == 'PersistentVolume':
            self.merge_dict(ret, {
                "metadata": {
                    "finalizers": [
                        "kubernetes.io/pv-protection"
                    ]
                },
                "spec": {
                    "persistentVolumeReclaimPolicy": "Retain"
                }
            }, overwrite=False)
        elif ret['kind'] == 'PersistentVolumeClaim':
            self.merge_dict(ret, {
                "metadata": {
                    "finalizers": [
                        "kubernetes.io/pvc-protection"
                    ]
                }
            }, overwrite=False)
        elif ret['kind'] == 'Route':
            self.merge_dict(ret, {
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
            }, overwrite=False)
            # If route host is generated, then need to blank out the host field to compare
            if ret['spec']['host'] == '':
                ret['metadata']['annotations']['openshift.io/host.generated'] = 'true'
            if ret['metadata']['annotations']['openshift.io/host.generated'] == 'true':
                ret['spec']['host'] = ''
        elif ret['kind'] == 'Service':
            self.merge_dict(ret, {
                "spec": {
                    "ports": lambda ports : self.port_list_defaults(ports),
                    "sessionAffinity": "None",
                    "sessionAffinityConfig": {
                        "clientIP": {
                            "timeoutSeconds": 10800
                        }
                    },
                    "type": "ClusterIP"
                }
            }, overwrite=False)

        return ret

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
                self.merge_dict(
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
        return triggers

    # Openshift drops the empty value strings, put those back to compare
    def empty_value_defaults(self, items):
         return self.merge_dict_list(
             items,
             { "value": "" },
             overwrite=False
         ),

    def port_list_defaults(self, items):
         return self.merge_dict_list(
             items,
             { "protocol": "TCP" },
             overwrite=False
         ),

    def imagestream_tags_defaults(self, tags):
         return self.merge_dict_list(
             tags,
             {
                 "referencePolicy": {
                     "type": "Source"
                 }
             },
             overwrite=False
         )

    def pod_volumes_defaults(self, volumes):
         return self.merge_dict_list(
             volumes,
             { "defaultMode": 0o644 },
             overwrite=False
         )

    def pod_template_defaults(self, pod_template):
        self.merge_dict(pod_template, {
            "spec": {
                "containers": lambda containers : self.merge_dict_list(
                    containers,
                    {
                        "env": lambda env : self.empty_value_defaults(env),
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
                        "ports": lambda ports : self.port_list_defaults(ports),
                        "readinessProbe": {
                            "httpGet": {
                                "scheme": "HTTP"
                            },
                            "initialDelaySeconds": 30,
                            "periodSeconds": 10,
                            "successThreshold": 1,
                            "failureThreshold": 3
                        },
                        "resources": {},
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
                "volumes": lambda volumes : self.pod_volumes_defaults(volumes)
            }
        }, overwrite=False)
        return pod_template

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

    def compare_resource(self, resource):
        if resource == None:
            return False

        a = self.filter_differences(self.resource)
        b = self.filter_differences(resource)
        for field in self.comparison_fields():
            if field in a and not field in b:
                if self.fail_on_change:
                    raise Exception(field + ' not in b')
                return False
            if field in b and not field in a:
                if self.fail_on_change:
                    raise Exception(field + ' not in a')
                return False
            if field in a and field in b and a[field] != b[field]:
                if self.fail_on_change:
                    raise Exception('a != b ' + field + json.dumps(a[field]) + json.dumps(b[field]))
                return False
        return True

    def check_patch(self, resource):
        '''return true if patch would not change resource'''
        if resource == None:
            raise Exception("Cannot patch %s %s, resource not found" % (
                self.resource['kind'], self.resource['metadata']['name']
            ))

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

    def provision(self):
        current_resource = self.get_current_resource()

        # Handle cases where no change will be applied
        if self.action == 'create':
            if current_resource:
                self.resource = current_resource
                return
        elif self.action == 'apply':
            if self.compare_resource(current_resource):
                self.resource = current_resource
                return
        elif self.action == 'patch':
            if self.check_patch(current_resource):
                self.resource = current_resource
                return
        elif self.action == 'replace':
            if current_resource == None:
                self.action = 'create'
            elif self.compare_resource(current_resource):
                self.resource = current_resource
                return
        elif self.action == 'delete':
            if current_resource == None:
                return
        elif self.action == 'ignore':
            return

        # Handle check mode by returning without applying change
        self.changed = True
        if self.module.check_mode:
            return

        # Apply changes
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
        else:
            command = [self.action, '-f', '-']
            if self.namespace:
                command += ['-n', self.namespace]
            # FIXME - Support other options such as
            # --cascade, --force, --overwrite, --prune, --prune-whitelist
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
            traceback=traceback.format_exc().split('\n'),
            resource=provisioner.resource
        )

    module.exit_json(changed=provisioner.changed, resource=provisioner.resource)

def main():
    run_module()

if __name__ == "__main__":
    main()
