Role Name
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
    
    openshift_clusters:
    - openshift_host_env: master.openshift.libvirt
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
          service_accounts:
          - name: jenkins
            cluster_roles:
            - self-provisioner
          user_to_role:
          - user: system:serviceaccount:app-dev:jenkins
            roles:
            - admin
    
        - name: app-prod
          environment_type: promotion
          display_name: CIPE production
          labels:
            application: app
          quotas:
          - name: compute
            spec: "{{ app_project_quota }}"
          user_to_role:
          - user: system:serviceaccount:app-dev:jenkins
            roles:
            - edit

License
-------

BSD

Author Information
------------------

Johnathan Kupferer (jkupfere@redhat.com)
