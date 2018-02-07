#!/usr/bin/python

import json
import tempfile
import re
import traceback
import copy


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
    - Action to perform on resource: apply, create, replace, delete
    default: apply
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
        for opt in ['server','certificate_authority','insecure_skip_tls_verify','token']:
            if opt in connection:
                self.oc_cmd += ['--' + opt.replace('_', '-') + '=' + connection[opt]]

    def merge_dict(self, merged, patch):
        for k, v in patch.iteritems():
            if type(v) is dict:
                if not k in merged:
                    merged[k] = copy.deepcopy(v)
                elif type(merged[k]) is dict:
                    self.merge_dict(merged[k], v)
                else:
                    raise "Unable to merge " + type(merged[key]) + " with dict"
            else:
                merged[k] = copy.deepcopy(v)

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
        if self.resource['kind'] == 'ImageStream':
            command = ['get']
        else:
            command = ['export']
        command += [self.resource['kind'], self.resource['metadata']['name'], '-o', 'json']
        if self.namespace:
            command += ['-n', self.namespace]
        (rc, stdout, stderr) = self.run_oc(command, check_rc=False)
        if rc != 0:
            return None
        return json.loads(stdout)

    def filter_differences(self, resource):

        if resource['kind'] == 'DaemonSet':
            filter = {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/last-applied-configuration": ""
                    },
                    "creationTimestamp": "",
                    "generation": 0,
                    "namespace": ""
                },
                "spec": {
                    "templateGeneration": 0
                }
            }
        elif resource['kind'] == 'Deployment':
            filter = {
                "metadata": {
                    "annotations": {
                        "deployment.kubernetes.io/revision": "0",
                        "kubectl.kubernetes.io/last-applied-configuration": ""
                    },
                    "creationTimestamp": "",
                    "generation": 0,
                    "namespace": ""
                },
                "spec": {
                    "template": {
                        "metadata": {
                            "creationTimestamp": ""
                        }
                    },
                    "templateGeneration": 0
                }
            }
        elif resource['kind'] in ['ReplicationController', 'ReplicaSet', 'StatefulSet']:
            filter = {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/last-applied-configuration": ""
                    },
                    "creationTimestamp": "",
                    "generation": 0,
                    "namespace": ""
                },
                "spec": {
                    "template": {
                        "metadata": {
                            "creationTimestamp": ""
                        }
                    }
                }
            }
        elif resource['kind'] == 'ImageStream':
            filter = {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/last-applied-configuration": "",
                        "openshift.io/image.dockerRepositoryCheck": "1970-01-01T00:00:00Z"
                    },
                    "creationTimestamp": "",
                    "generation": 0,
                    "namespace": "",
                    "resourceVersion": "0",
                    "selfLink": "",
                    "uid": ""
                }
            }
        elif resource['kind'] == 'PersistentVolume':
            filter = {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/last-applied-configuration": "",
                        "pv.kubernetes.io/bound-by-controller": ""
                    },
                    "creationTimestamp": "",
                    "generation": 0,
                    "namespace": ""
                },
                "spec": {
                    "claimRef": ""
                }
            }
        else:
            filter = {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/last-applied-configuration": ""
                    },
                    "creationTimestamp": "",
                    "generation": 0,
                    "namespace": ""
                }
            }

        ret = self.merge(resource, filter)

        if ret['kind'] == 'ImageStream':
            for tag in ret['spec']['tags']:
                tag['generation'] = 0
                if not 'referencePolicy' in tag:
                    tag['referencePolicy'] = {'type': 'Source'}
            if not 'lookupPolicy' in ret['spec']:
                ret['spec']['lookupPolicy'] = {'local': False}
        elif ret['kind'] == 'StatefulSet':
            for claimtemplate in ret['spec']['volumeClaimTemplates']:
                claimtemplate['metadata']['creationTimestamp'] = ""
                claimtemplate['status'] = {}

        return ret

    def comparison_fields(self):
        if self.resource['kind'] == 'ClusterRole':
          return ['metadata', 'rules']
        elif self.resource['kind'] in ['ConfigMap', 'Secret']:
          return ['metadata', 'data']
        elif self.resource['kind'] == 'ServiceAccount':
          return ['metadata', 'imagePullSecrets', 'secrets']
        elif self.resource['kind'] == 'Template':
          return ['metadata', 'labels', 'objects', 'parameters']
        else:
          return ['metadata', 'spec']

    def compare_resource(self, resource):
        if resource == None:
            return False

        a = self.filter_differences(self.resource)
        b = self.filter_differences(resource)
        for field in self.comparison_fields():
            if field in a and not field in b:
                return False
            if field in b and not field in a:
                return False
            if field in a and field in b and a[field] != b[field]:
                return False
        return True

    def provision(self):
        current_resource = self.get_current_resource()

        if self.action == 'create':
            if current_resource:
                self.resource = current_resource
                return
        elif self.action == 'apply' or self.action == 'replace':
            if self.compare_resource(current_resource):
                self.resource = current_resource
                return
        elif self.action == 'delete':
            if current_resource == None:
                return

        if self.action == 'delete':
            command = ['delete', self.resource['kind'], self.resource['metadata']['name']]
            if self.namespace:
                command += ['-n', self.namespace]
            (rc, stdout, stderr) = self.run_oc(command, check_rc=True)
        else:
            command = [self.action, '-f', '-']
            if self.namespace:
                command += ['-n', self.namespace]
            (rc, stdout, stderr) = self.run_oc(command, data=json.dumps(self.resource), check_rc=True)

        self.changed = True

def run_module():
    module_args = {
        'action': {
            'type': 'str',
            'required': False,
            'default': 'apply'
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
            msg=e.message,
            traceback=traceback.format_exc().split('\n'),
            resource=provisioner.resource
        )

    module.exit_json(changed=provisioner.changed, resource=provisioner.resource)

    if module.check_mode:
        return

def main():
    run_module()

if __name__ == "__main__":
    main()
