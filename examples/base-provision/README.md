# Cluster Base Provisioning Example

This example shows using openshift-provision to setup basic cluster
infrastructure of the sort that would immediately follow cluster installation
or configuration with the
[openshift-ansible playbooks](https://github.com/openshift/openshift-ansible).

While other examples need to provide authentication and connection information,
in this case we assume that our playbook can run directly on the cluster
masters as root and so have full privileged access to provision resources in
the cluster.

For most provisioning tasks we would prefer to run with minimal permissions.
We show here setting up a central CICD service account and a project in which
we may run Jenkins agents to integrate with an external Jenkins server.

## The `provision.yml` Playbook

We run directly on the first (or only) master server. This requires that the
inventory have a group "masters" with at least one master listed. Typically
this would be the same inventory that was used to run the `openshift-ansible`
playbooks to install and configure the cluster.

The root user is normally logged in as system:admin. If the root user becomes
logged out or logged in as a different user it may be necessary to copy over
`/etc/origin/master/admin.kubeconfig` to `/root/.kube/config` to restore login,
or as we do here, just explicitly point to `/etc/origin/master/admin.kubeconfig`

```yaml
# Run directly on a master within the cluster for full access.
- name: Base Provision
  hosts: masters[0]
  vars:
    oc_cmd_base: oc --config=/etc/origin/master/admin.kubeconfig
  vars_files:
  - provision/base.yml
  roles:
  - role: openshift-provision
```

See comments in provisino/base.yml for more on this example.
