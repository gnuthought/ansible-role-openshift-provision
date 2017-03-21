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
    
          openshift_resources:
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
              user_to_role:
              - user: system:serviceaccount:app-dev:jenkins
                roles:
                - edit
              group_to_role:
              - group: app-developer
                roles:
                - edit
              - group: app-admin
                roles:
                - admin
    
        - name: app-prod
          environment_type: promotion
          display_name: Application production
          labels:
            application: appname
          quotas:
          - name: compute
            spec: "{{ app_project_quota }}"
          user_to_role:
          - user: system:serviceaccount:app-dev:jenkins
            roles:
            - edit
          group_to_role:
          - group: app-developer
            roles:
            - view
          - group: app-admin
            roles:
            - admin

License
-------

BSD

Author Information
------------------

Johnathan Kupferer (jkupfere@redhat.com)
