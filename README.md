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
           resource_definition: ocp/resources.yml

License
-------

BSD

Author Information
------------------

Johnathan Kupferer (jkupfere@redhat.com)
