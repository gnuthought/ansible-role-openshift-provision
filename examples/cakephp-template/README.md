# CakePHP Example using OpenShift Template

This example shows using the OpenShift CakePHP example application to
demonstrate how an application can be deployed using openshift-provision from
an OpenShift template.

The template used in this example is based off the OpenShift template
cakephp-mysql-example provided in the openshift namespace. A few changes were
made to the template to support idempotent deployment using
openshift-provision. The modifications to the template are described below.

## Usage

The simplest way to use this example is to login to your OpenShift environment
with the `oc` commandline and running:

```bash
$ ansible-playbook playbook.yml
```

The `ansible.cfg` expects to find the openshift-provision role in a parent
directory and for that directory to be named "openshift-provision". If you
checked out this git repository into a directory named
"ansible-role-openshift-provision" then you may need to rename it to
"openshift-provision" to use these examples.

The playbook provided will create the target project if it doesn't exist
and populate it with the resources created from the template. Variables are
defined in `vars.yml` that set parameters passed to template processing and
may be overridden with extra vars to the ansible-playbook command.

* `app_name` - Used for the `NAME` parameter as well as project name in which to
  create the template.

* `app_build_github_webhook_secret` - Value used for the parameter
  `GITHUB_WEBHOOK_SECRET`

* `app_memory_limit` - Value used for the parameter `MEMORY_LIMIT`

## Idempotent Template Processing

What makes template processing with openshift-provision so useful is that it
takes the output of template processing and checks the current state of each
resource against the template definition, only updating resources if the
definition differs.

For example, running the following will only update the DeploymentConfig:

```bash
$ ansible-playbook playbook.yml -e app_memory_limit=600Mi
```

If you only want to compare the current state against the template definition
then you can run the playbook in check mode:

```bash
$ ansible-playbook playbook.yml -e app_memory_limit=1Gi --check
```

## Template Adjustments

In order to insure idempotent processing the template adds an annotation that
tells openshift-provision to only process the Secret in create mode and skip
modifying it later so that it won't change password and other values that
are randomly generated when first run.

```diff
   kind: Secret
   metadata:
     name: ${NAME}
+    annotations:
+      openshift-provision/action: create
   stringData:
     cakephp-secret-token: ${CAKEPHP_SECRET_TOKEN}
     cakephp-security-cipher-seed: ${CAKEPHP_SECURITY_CIPHER_SEED}
     cakephp-security-salt: ${CAKEPHP_SECURITY_SALT}
     database-password: ${DATABASE_PASSWORD}
     database-user: ${DATABASE_USER}
```

The ImageStream is initialized empty, but will change to add a "latest" tag
as soon as the first build completes, so we also handle the ImageStream with
the create action mode.

```diff
 - apiVersion: v1
   kind: ImageStream
   metadata:
     annotations:
       description: Keeps track of changes in the application image
+      openshift-provision/action: create
     name: ${NAME}
```

The MySQL readinessProbe is redefined to use available environment variables
rather than directly referencing the template parameters. This prevents
this probe from being updated later with new random values. The environment
variables are set using the downward api, getting their values from the
Secret.

```diff
           readinessProbe:
             exec:
               command:
               - /bin/sh
               - -i
               - -c
-              - MYSQL_PWD='${DATABASE_PASSWORD}' mysql -h 127.0.0.1 -u ${DATABASE_USER}
-                -D ${DATABASE_NAME} -e 'SELECT 1'
+              - MYSQL_PWD="${MYSQL_PASSWORD}" mysql -h 127.0.0.1 -u ${MYSQL_USER} -D ${MYSQL_DATABASE} -e 'SELECT 1'
             initialDelaySeconds: 5
             timeoutSeconds: 1
```

The GitHub trigger secret ends up in the DeploymentConfig. If we randomly
generated a new value on each run it would change the trigger on every run.
This isn't appropriate behavior so we insist that it must be explicitly
defined when the template is processed.

```diff
 - description: Github trigger secret.  A difficult to guess string encoded as part
     of the webhook URL.  Not encrypted.
   displayName: GitHub Webhook Secret
-  from: '[a-zA-Z0-9]{40}'
-  generate: expression
+  required: true
   name: GITHUB_WEBHOOK_SECRET
```
