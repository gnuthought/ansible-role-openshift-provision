openshift-provision
=========

An Ansible role for provisioning resources within OpenShift clusters.

This role provides comprehensive OpenShift cluster resource provisioning
using a declarative variable structure with multi-level resource definition
lookups and template automation.

The openshift-provision ansible role may be used directly or using a
containerized deployment pattern provided by the
[openshift-provision-manager](https://github.com/gnuthought/openshift-provision-manager).

Project Goals
-------------

Management of OpenShift resources should be:

* **Agnostic** - allow management of any resource or custom resource type should
  be managable to configure any desired state.

* **Easy** - easy things should be easy...

* **Flexible** - ... and hard things should be possible.

* **Compatible** - compatible with tools already in development workflow such
  as OpenShift templates (Helm charts support is on the project roadmap).

* **Idempotent** - possible to run the tool repeatedly without changing the
  state.

* **Robust** - able to converge from any configuration state, even when the
  resource was managed by hand.

* **Reportable** - able to produce accurate reports of what is changed.

* **Auditable** - able to produce a report of differences of current state from
  desired state without changing anything.

* **Traceable** - resources configured by the management system should be
  obvious (feature is on the roadmap).

* **Stateful** - resources from previous processing should be tracked in a way
  to allow rollback and cleanup (feature is on the roadmap).


Contact
-------

Whether looking to contribute or just looking for some info, you can find us
on ...

Slack: https://gnuthought.slack.com/messages/openshift-provision/

Trello: https://trello.com/b/icRRuDUS/openshift-provision


Installation
------------

```
ansible-galaxy install https://github.com/gnuthought/ansible-role-openshift-provision/archive/master.tar.gz#/openshift_provision
```

Requirements
------------

OpenShift 3.9, 3.11, 4.0, 4.5, and 4.6
Ansible 2.4+ with Python 2.7+

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

* `generate_resources` - A flag to generate resources as json files
  rather than provisioning them. Defaults to `False`. See
  [additional notes on the generate_resources flag](#Additional-notes-on-the-generate_resources-flag)
  for more details.

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

* `openshift_provision_change_record` - Local filename in which to record all
  changes between current state and configured state.

* `openshift_resource_path` - Default list of directories to search for file
  paths in cluster and project `cluster_resources` and `resources` definitions.
  Default to playbook directory

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

* `change_record` - Local filename in which to record all changes between
  current state and configured state. Defaults to
  `openshift_provision_change_record`

* `cluster_resources` - List of OpenShift resource definitions, these should
  be cluster level resources. Resources may be specified by a file path
  or inline OpenShift resource definition. If a file path is used it will be
  found using the value of `resource_path`. If the filename ends in ".j2"
  then it will be processed as a Jinja2 template.

* `cluster_role_bindings` - List of roles and assigned users and groups,
  described below

* `groups` - List of OpenShift groups to create along with group membership,
  described below

* `helm_charts` - Helm chart templates to deploy to the cluster. Note that
  helm charts can also be managed at the project level.

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

* `role` - Name of cluster role for which role bindings are managed. Required

* `users` - List of user names that should be granted access to this cluster
  role. Optional

* `groups` - List of group names that should be granted access to this cluster
  role. Optional

* `remove_unlisted` - Boolean to indicate whether users, or groups not listed
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

* `remove_unlisted` - Boolean to indicate whether members not listed
  should be removed from this group. Optional,
  default "false"

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

* `helm_charts` - Helm chart templates to deploy to the project namespace.

* `join_pod_network` - Name of target project to which this project network
  should be joined for use with multi-tenant SDN

* `labels` - Dictionary of project labels

* `multicast_enabled` - Boolean value indicating whether multicast should
  be enabled in the annotations on this project's netnamespace

* `node_selector` - Node selector to apply to the project namespace

* `process_templates` - Templates to process to create resources within this
  project, described below

* `remove_unlisted` - Boolean to indicate whether labels or annotations not listed
  should be removed from this project. Optional,
  default "false"

* `remove_unlisted_labels` - Same as `remove_unlisted`, but specifically
  targeting labels. Optional, default "false"

* `remove_unlisted_annotations` - Same as `remove_unlisted`, but specifically
  targeting annotations. Optional, default "false"

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

* `role` - Names the role to be managed. This can be the name of a ClusterRole
  or the name of a namespace Role given as `{{namespace}}/{{rolename}}`.
  Required

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

### `helm_charts`

Helm charts are supported as a means of templating resources into the cluster.
Helm support is provided without tiller or helm lifecycle hooks. Only fetching
and templating helm charts is supported. If full helm lifecycle management is
required then openshift-provision may be leveraged to deploy tiller into the
cluster.

The value of `helm_charts` should be a list of dictionaries where each
dictionary contains:

* `name` - template release name, Optional
* `action` - provision action, Optional, default: 'apply'
* `chart` - chart to template, may be local path or chart name
* `chart_values` - values for chart processing
* `fetch` - options used for helm fetch, Optional
  * `chart` - chart argument to `helm fetch`
  * `ca_file` - verify certificates of HTTPS-enabled servers using this CA bundle
  * `cert_file` - identify HTTPS client using this SSL certificate file
  * `devel` - boolean, use development versions
  * `key_file` - identify HTTPS client using this SSL key file
  * `password` - chart repository password
  * `repo` - chart repository url where to locate the requested chart
  * `username` - chart repository username
  * `version` - specific version of a chart. Without this, the latest version is fetched

### `resources`

List of OpenShift project resources to create. Declaration is the same as
specified above for `projects[*].resources` with the
addition that each entry here must specify `metadata.namespace` to specify
the target project for the resource.

### Additional notes on the `generate_resources` flag

* All files will be created in a directory named `manifests` in the format
  `<scope>_<kind>_<name>.json` where:
  * `scope` is "cluster" for a cluster resource, or the target namespace name
  * `kind` is the Kubernetes resource kind
  * `name` is the metadata name for the resource
* If a project does not exist, this role will still attempt to create the project.
* Modification actions to a resource requires the resource to exist so it can be
  used for comparison.
* If service accounts, role bindings, and cluster role bindings are defined as
  `service_accounts`, `role_bindings`, and `cluster_role_bindings` variables,
  the role will attempt to apply them. If you want them to be generated, you
  would have to define them as you would any other resource.

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
        - apiVersion: v1
          kind: ResourceQuota
          metadata:
            name: compute
          spec:
            hard:
              requests.cpu: "10"
              requests.memory: "50Gi"
              limits.cpu: "20"
              limits.memory: "50Gi"
        - apiVersion: v1
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
