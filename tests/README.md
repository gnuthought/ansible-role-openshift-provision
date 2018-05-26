# Test Suite for openshift-provision Ansible Role

## Preparing for testing with minishift

```bash
$ oc login -u system:admin
$ oc create sa -n default provisioner
$ oc adm policy add-cluster-role-to-user system:serviceaccount:default:provisioner
$ TOKEN=$(oc sa get-token -n default provisioner)
$ sed "s/openshift_connection_token: .*/openshift_connection_token: $TOKEN/" login-creds.yml.example >login-creds.yml
```

## Running the test suite

```bash
$ ./test.sh
```
