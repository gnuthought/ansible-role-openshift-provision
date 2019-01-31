openshift-provision
=========

An Ansible role for provisioning resources within OpenShift clusters.

This role provides comprehensive OpenShift cluster resource provisioning
using a single declarative variable structure or using the
`openshift_provision` Ansible module provided.

Installation
------------

```
ansible-galaxy install https://github.com/gnuthought/ansible-role-openshift-provision/archive/master.tar.gz#/openshift-provision
```

Requirements
------------

OpenShift 3.4, 3.5, 3.7, 3.9, 3.10, & 3.11
ansible 2.4+ with Python 2.7+

A host with the `oc` command to run from.

Usage
-----

The `openshift_provision` role may be run from any host with the `oc` command
and access to the cluster with appropriate privileges to provision the
resources specified in the calling playbook. For provisioning base cluster
configuration it is recommended to run `openshift_provision` from a master node
immediately following OpenShift cluster installation. For provisioning
application projects and resources it is recommended to use another host,
authenticating with a service account token. Username with password login is
supported with the `openshift_login` module. The host processing the
`openshift_provision` role must have the `oc` command and the Python JMESPath
module for supporting the `json_query` ansible filter.

If this role is called with a `openshift_resource_definition` file variable, it will read
variables from the file specified.

Role Variables
--------------

* `oc_cmd_base` - The base `oc` command. Defaults to "oc", but can be set to
  specify a different path or add custom options

* `openshift_clusters` - List of openshift cluster definitions as described
  below. If a single cluster is being configured then `openshift_provision`
  may be used instead.

* `openshift_cluster_provision_post_tasks` - List of ansible tasks files to
  include after processing provision for each cluster

* `openshift_cluster_provision_pre_tasks` - List of ansible tasks files to
  include immediately before processing provision for each cluster

* `openshift_connection_certificate_authority` - Path to file containing
  signing certificate for OpenShift server. This option may also be set within
  `openshift_clusters` as `connection.certificate_authority`

* `openshift_connection_insecure_skip_tls_verify` - If set to "true" then
  disable SSL/TLS checks when connectiong to OpenShift server. This option
  may also be set within `openshift_clusters` as
  `connection.insecure_skip_tls_verify`

* `openshift_connection_server` - Server URL for connecting to the OpenShift
  cluster. Should by of the form "https://master.example.com:8443". This option
  may also be set within `openshift_clusters` as `connection.server`

* `openshift_connection_token` - OpenShift user token. This option may also be
  set within `openshift_clusters` as `connection.token`

* `openshift_login_username` - Login username. Use of a connection token is
  preferred to providing a username and password. This option may also be
  set within `openshift_clusters` as `login.username`

* `openshift_login_password` - Login password. Use of a connection token is
  preferred to providing a username and password. This option may also be
  set within `openshift_clusters` as `login.password`

* `openshift_provision` - Variable for single cluster management, ignored
  if `openshift_clusters` is set.

* `openshift_resource_path` - Default list of directories to search for file
  paths in cluster and project `cluster_resources` and `resources` definitions.
  Default to playbook directory

* `openshift_resource_definition` (DEPRECATED) - Path to variable definitons
  to dynamically load with `include_vars`. Use of standard Ansible variable
  mechanisms is recommended

* `user_groups` (DEPRECATED) - List of groups to create across all clusters,
  use of `groups` under `openshift_clusters` is preferred

### `openshift_provision` or `openshift_clusters[*]`

Top level definition of how to manage a cluster:

* `connection` - OpenShift connection parameters, defined to match `oc` command
  line including `server`, `certificate_authority`, `insecure_skip_tls_verify`,
  and `token`. If omitted then it is assumed the environment is already has a
  valid OpenShift command line login session

* `login` - Credentials for login to the OpenShift cluster, `username` and
  `password`

* `openshift_host_env` - String or array of strings specifying hostnames. The
  cluster resources will only be provisioned if this variable is not set or if
  `openshift_master_cluster_public_hostname` equals a value in
  `openshift_host_env`

* `cluster_resources` - List of OpenShift resource definitions, these should
  be cluster level resources. Resources may be specified by a file path
  or inline OpenShift resource definition. If a file path is used it will be
  found using the value of `resource_path`. If the filename ends in ".j2"
  then it will be processed as a Jinja2 template.

* `cluster_role_bindings` - List of roles and assigned users and groups,
  described below

* `groups` - List of OpenShift groups to create along with group membership,
  described below

* `process_templates` - Templates to process to create resources at the
  cluster level, described below

* `projects` - List of projects to manage, described below:

* `provision_post_tasks` - List of ansible tasks files to include after
  processing provision this cluster

* `provision_pre_tasks` - List of ansible tasks files to include immediately
  before processing provision for this cluster

* `resource_path` - List of paths to search for resource definitons specified
  by relative file path under `cluster_resources` and `resources`, defaults
  to value of `openshift_resource_path`

* `resources` - List of OpenShift resource definitions, these should be
  project level resources that define the namespace. Normally project resources
  should appear within `projects`, but sometimes specific ordering of resource
  creation may be desired. Resources are defined in the same manner as
  `cluster_resources`

* `persistent_volumes` (DEPRECATED) - List of persistent volumes. Use of
  `cluster_resources` is preferred

* `cluster_resource_quotas` (DEPRECATED) - List of cluster resource quota
  definitions. Use of `cluster_resources` is preferred

* `cluster_roles` (DEPRECATED) - List of OpenShift cluster role definitions.
  Use of `cluster_resources` is preferred

### `openshift_provision.cluster_resources` or `openshift_clusters[*].cluster_resources`

Cluster resources are the first items processed in provisioning. This is a
list of OpenShift resource definitions that are created/updated using the `oc`
command. The default action is `oc apply`, but may be overridden by setting
"metadata.annotations.openshift-provision/action" on the resource. Values for
action may be:

* `apply` - Use `oc apply` to create or update the resource

* `create` - Use `oc create` to create the resource. If the resource already
  exists then no action is taken

* `delete` - Use `oc delete` to delete the resource. If the resource does not
  exist then no action is taken

* `patch` - Use `oc patch` to update the resource. If the resource does not
  exist then an error is thrown

* `replace` - Use `oc replace` to update the resource. If the resource does not
  exist then it is created with `oc create`

Besides the field `action` all other fields follow OpenShift standards. All
resources must define `metadata.name`.

### `cluster_role_bindings`

List of cluster role assignments. Each entry is a dictionary containing:

* `role` - Name of role managed. This is *not* the name name of rolebinding,
  but rather the name of the role referenced by the role binding. Assignment
  and removal of roles uses `oc adm policy` commands which do not specify the
  name of role bindings. Required

* `users` - List of user names that should be granted access to this cluster
  role. Optional

* `groups` - List of group names that should be granted access to this cluster
  role. Optional

* `remove_unlisted` - Boolean to indicate whether users or groups not listed
  should be removed from any current access to this cluster role. Optional,
  default "false"

* `remove_unlisted_users` - Same as `remove_unlisted`, but specifically
  targeting users. Optional, default "false"

* `remove_unlisted_groups` - Same as `remove_unlisted`, but specifically
  targeting groups. Optional, default "false"

### `groups`

List of OpenShift groups to manage

* `name` - Group name. Required

* `members` - List of user names that should belong to this group. Optional

* `remove_unlisted_members` - Boolean to indicate whether unlisted users should
  be removed from this group. Optional, default "false"

### `process_templates`

List of templates to process to manage resources for the cluster. The result
items list from the processed template is then parsed and each resource in
that list is processed by `openshift_provision`.

* `file` - Filename or URL to use for template source, mutually exclusive with
  `name`

* `name` - Template name to process, mutually exclusive with `file`

* `namespace` - Namespace in which the template specified in `name` is found,
  default is this project

* `parameters` - Dictionary of parameters to pass to the template. Optional

* `action` - Action to process template output, values for `action` are the same
  as described for above for `openshift_clusters[*].cluster_resources`.

* `patch_type` - Patch type to use when action is "patch".

### `projects`

* `name` - Project name string

* `admin_create` - Boolean flag to indicate if projects should be created with
  `oc adm new-project`, otherwise `oc new-project` is used. Defaults to false.

* `annotations` - Dictionary of project annotations

* `description` - Project description string

* `display_name` - Project display name string

* `imagestreams` - Names of imagestreams to create in the project. This
   parameter is meant to allow for simple creation of imagestreams such as are
   created by `oc create imagestream NAME`. For more sophisticated imagestream
   creation a full definition may be provided within `resources`

* `join_pod_network` - Name of target project to which this project network
  should be joined for use with multi-tenant SDN

* `labels` - Dictionary of project labels

* `multicast_enabled` - Boolean value indicating whether multicast should
  be enabled in the annotations on this project's netnamespace

* `node_selector` - Node selector to apply to the project namespace

* `process_templates` - Templates to process to create resources within this
  project, described below

* `resource_path` - List of paths to search for resource definitons specified
  by relative file path under `resources`, defaults to `resource_path` value at
  cluster level

* `resources` - Definitions of OpenShift resources to create in project.
  Resources may be specified by a file path or inline OpenShift resource
  definition. If a file path is used it will be found using the value of
  `resource_path`. If the filename ends in ".j2" then it will be processed as a
  Jinja2 template.

* `role_bindings` - Role bindings to apply to project to grant or revoke user
  and group access to roles, described below

* `service_accounts` - List of service accounts to provision within this
  project. Each entry is a name of a service account to create. Service
  accounts may also be created with `resources`, which allows for specifying
  `secrets` and `imagePullSecrets`.

* `limit_ranges` (DEPRECATED) - List of limit ranges to apply to project, use
  of `resources` is preferred to create LimitRange objects

* `persistent_volume_claims` (DEPRECATED) - List of persistent volume claims
  for project, use of `resources` is preferred to create PersistentVolumeClaim
  objects

* `quotas` (DEPRECATED) - List of quotas to apply to project, use of
  `resources` is preferred to create ResourceQuota objects

### `projects[*].process_templates`

List of templates to process to manage resources within project. The result
items list from the processed template is then parsed and each resource in
that list is processed by `openshift_provision`.

* `name` - Template name to process

* `namespace` - Namespace in which the template is found, default is this
  project

* `parameters` - Dictionary of parameters to pass to the template. Optional

* `action` - Action to process template output, values for `action` are the same
  as described for above for `cluster_resources`.

* `patch_type` - Patch type to use when action is "patch".

### `projects[*].resources`

This is a list of OpenShift resource definitions that are created/updated in
a project using the `oc` command. The default action is `oc apply`, but may be
overridden by setting the annotation "openshift-provision/action" within the
resource. Values for `action` are the same as described above for
`cluster_resources`. The annotation
"openshift-provision/patch-type" may be used with the "patch" action.

### `projects[*].role_bindings`

List of project role assignments. Each entry is a dictionary containing:

* `role` - Name of role managed. This is *not* the name name of rolebinding,
  but rather the name of the role referenced by the role binding. Assignment
  and removal of roles uses `oc policy` commands which do not specify the
  name of role bindings. Required

* `users` - List of user names that should be granted access to this project
  role. Optional

* `groups` - List of group names that should be granted access to this project
  role. Optional

* `remove_unlisted` - Boolean to indicate whether users or groups not listed
  should be removed from any current access to this project role. Optional,
  default "false"

* `remove_unlisted_users` - Same as `remove_unlisted`, but specifically
  targeting users. Optional, default "false"

* `remove_unlisted_groups` - Same as `remove_unlisted`, but specifically
  targeting groups. Optional, default "false"

### `resources`

List of OpenShift project resources to create. Declaration is the same as
specified above for `projects[*].resources` with the
addition that each entry here must specify `metadata.namespace` to specify
the target project for the resource.

Example Playbook with Provisioning by Role Variables
----------------------------------------------------

    - hosts: masters[0]
      roles:
         - role: openshift-logging-elasticsearch-hostmount
           resource_definition: ocp-resouces/app.yml

Example resources file:

    openshift_provision:
      connection:
        server: https://openshift-master.libvirt:8443
        token: abcdefghijklmnopqrstuvwxyz0123456798...

      cluster_resources:
      - apiVersion: v1
        kind: ClusterRole
        metadata:
          creationTimestamp: null
          name: network-joiner
        rules:
        - apiGroups:
          - network.openshift.io
          - ""
          attributeRestrictions: null
          resources:
          - netnamespaces
          verbs:
          - create
          - delete
          - get
          - list
          - update
        - apiGroups:
          - ""
          attributeRestrictions: null
          resources:
          - namespaces
          - projects
          verbs:
          - get
          - list
        - apiGroups:
          - network.openshift.io
          - ""
          attributeRestrictions: null
          resources:
          - clusternetworks
          verbs:
          - get
      - apiVersion: v1
        kind: ClusterResourceQuota
        metadata:
          creationTimestamp: null
          name: serviceaccount-app-jenkins
        spec:
          quota:
            hard:
              limits.cpu: "10"
              limits.memory: 20Gi
              requests.cpu: "5"
              requests.memory: 20Gi
          selector:
            annotations:
              openshift.io/requester: system:serviceaccount:app-dev:jenkins
            labels: null
      - apiVersion: v1
        kind: PersistentVolume
        metadata:
          creationTimestamp: null
          labels:
            foo: bar
          name: nfs-foo
        spec:
          access_modes:
          - ReadWriteMany
          capacity:
            storage: 10Gi
          nfs:
            path: /export/foo
            server: nfsserver.example.com
          persistentVolumeReclaimPolicy: Retain

      cluster_role_bindings:
      - role: self-provisioner
        users:
        - system:serviceaccount:app-dev:jenkins
      - role: network-joiner
        users:
        - system:serviceaccount:app-dev:jenkins
        groups:
        - app-admin
        remove_unlisted: true

      groups:
      - name: app-admin
        remove_unlisted_members: true
        members:
        - alice
        - bob

      projects:
      - name: app-dev
        description: Application Description
        display_name: Application Name
        labels:
          application: appname
        node_selector: region=app

        process_templates:
        - name: httpd-example
          namespace: openshift
          parameters:
            SOURCE_REPOSITORY_URL: https://github.com/openshift/httpd-ex.git

        resources:
        - appVersion: v1
          kind: ResourceQuota
          metadata:
            name: compute
          spec:
            hard:
              requests.cpu: "10"
              requests.memory: "50Gi"
              limits.cpu: "20"
              limits.memory: "50Gi"
        - appVersion: v1
          kind: LimitRange
          metadata:
            name: compute
          spec:
            limits:
            - type: Pod
              min:
                cpu: 50m
                memory: 4Mi
              max:
                cpu: "2"
                memory: 5Gi
            - type: Container
              min:
                cpu: 50m
                memory: 4Mi
              max:
                cpu: "2"
                memory: 5Gi
              default:
                cpu: "1"
                memory: 1Gi
              defaultRequest:
                cpu: 200m
                memory: 1Gi

        role_bindings:
        - role: admin
          groups: app-admin
          remove_unlisted: true
        - role: edit
          users:
          - system:serviceaccount:app-dev:jenkins
          remove_unlisted_users: true
        - role: view
          groups:
          - app-developer

        service_accounts:
        - jenkins

Example Playbook with Provisioning with `openshift_provision` Module
--------------------------------------------------------------------

    - hosts: localhost
      connection: local
      gather_facts: no
      vars:
        openshift_connection:
          server: "{{ openshift_connection_server }}"
          token: "{{ openshift_connection_token }}"
      roles:
      - role: openshift-logging-elasticsearch-hostmount

      tasks:
      - name: Provision BuildConfig
        openshift_provision:
          connection: "{{ openshift_connection }}"
          namespace: example-project
          resource:
            apiVersion: v1
            kind: BuildConfig
            metadata:
              name: test-buildconfig
            spec:
              nodeSelector: null
              output:
                to:
                  kind: ImageStreamTag
                  name: testbuild:latest
              postCommit: {}
              resources: {}
              runPolicy: Serial
              source:
                git:
                  uri: https://nosuch.example.com/blah.git
                type: Git
              strategy:
                sourceStrategy:
                  from:
                    kind: ImageStreamTag
                    name: httpd:2.4
                    namespace: openshift
                type: Source
              triggers: []

Example with Provisioning with `openshift_provision` Module and Login
---------------------------------------------------------------------

    - hosts: localhost
      connection: local
      gather_facts: no
      vars:
        openshift_connection:
          server: "{{ openshift_connection_server }}"
          token: "{{ openshift_connection_token }}"
      roles:
      - role: openshift-logging-elasticsearch-hostmount

      tasks:
      - name: Login to OpenShift Cluster
        openshift_login:
          username: username
          password: password
          server: https://openshift-master.libvirt
          insecure_skip_tls_verify: "true"
        register: openshift_login

      - name: Provision Resource
        openshift_provision:
          connection: "{{ openshift_login.session }}"
          resource:
            apiVersion: v1
            kind: PersistentVolumeClaim
            metadata:
              name: test-persistentvolumeclaim
              labels:
                testlabel: bar
            spec:
              accessModes:
              - ReadWriteOnce
              resources:
                requests:
                  storage: 1Gi

License
-------

BSD

Author Information
------------------

Johnathan Kupferer (jkupfere@redhat.com)
