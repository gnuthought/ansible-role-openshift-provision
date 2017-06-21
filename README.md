openshift-provision
=========

An Ansible role for provisioning resources within OpenShift clusters.

Installation
------------

```
ansible-galaxy install https://github.com/jkupferer/ansible-role-openshift-provision/archive/master.tar.gz#/openshift-provision
```

Requirements
------------

OCP 3.3 or 3.4

Role Variables
--------------

* `resource_definition` - Ansible variables file definining resources to create

Example Playbook
----------------

    - hosts: masters[0]
      roles:
         - role: openshift-logging-elasticsearch-hostmount
           resource_definition: ocp-resouces/app.yml

Example resources file:

    app_project_quota:
      hard:
        requests.cpu: "10"
        requests.memory: "50Gi"
        limits.cpu: "20"
        limits.memory: "50Gi"

    app_limit_range:
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

    user_groups:
    - name: app-admin
      remove_unlisted_members: true
      members:
      - alice
      - bob
    
    openshift_clusters:
    - openshift_host_env: master.openshift.libvirt

      cluster_roles:
      - metadata:
          name: network-joiner
        rules:
        - apiGroups:
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
          - watch
        - apiGroups:
          - ""
          attributeRestrictions: null
          resources:
          - namespaces
          - projects
          verbs:
          - get
          - list

      cluster_role_bindings:
      - role: self-provisioner:
        user: system:serviceaccount:app-dev:jenkins

      cluster_resource_quotas:
      - name: serviceaccount-app-jenkins
        spec:
          quota:
            hard:
              requests.cpu: "5"
              requests.memory: "20Gi"
              limits.cpu: "10"
              limits.memory: "20Gi"
          selector:
            annotations:
              openshift.io/requester: system:serviceaccount:app-dev:jenkins

      persistent_volumes:
    
      - name: pv01
        capacity: 10
        access_modes:
        - ReadWriteMany
        nfs_path: /blash
        nfs_server: someserver.eample.com
        reclaim_policy: Recycle
        labels:
          foo: bar
    
      - name: pv01
        capacity: 10
        access_modes:
        - ReadWriteMany
        nfs:
          path: /blash
          server: someserver.eample.com
        reclaim_policy: Recycle
        labels:
          foo: bar2
    
      projects:
        
      - name: app-dev
        display_name: Application development
        environment_type: build
        labels:
          application: appname
        quotas:
        - name: compute
          spec: "{{ app_project_quota }}"
        limit_ranges:
        - name: compute
          spec: "{{ app_limit_range }}"
        service_accounts:
        - name: jenkins
        role_bindings:
        - role: admin
          groups: app-admin
          remove_unlisted: true
        - role: edit
          users:
          - system:serviceaccount:app-dev:jenkins
          groups:
          - app-developer
          remove_unlisted_groups: true
    
      - name: app-prod
        environment_type: promotion
        display_name: Application production
        labels:
          application: appname
        quotas:
        - name: compute
          spec: "{{ app_project_quota }}"
        role_bindings:
        - role: admin
          groups: app-admin
          remove_unlisted: true
        - role: edit
          users:
          - system:serviceaccount:app-dev:jenkins
          remove_unlisted: true
        - role: view
          groups:
          - app-developer
          remove_unlisted: true

License
-------

BSD

Author Information
------------------

Johnathan Kupferer (jkupfere@redhat.com)
