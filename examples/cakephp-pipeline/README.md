# Application Pipeline Example with CakePHP

This example shows how to implement an application pipeline using
openshift-provision. This pipeline has separate projects for "build", "dev",
"stage", and "prod". Images are built in "build" then deployed through
successive environments up to prod.

There are three playbooks provided in the example:

* `pipeline-setup.yml` - Sets up the pipeline projects with MySQL deployment,
  Secrets, ServiceAccounts and RoleBindings needed for the other playbooks.

* `app-build.yml` - Manages the application BuildConfig and starts the build

* `app-deploy.yml` - Deploys application configuration and promotes the
  application image from lower to higher environments

All three of these playbooks are fully idempotent and support Ansible check
mode.

## Usage

Before you launch the project pipeline setup you will need to create a
`login-creds.yml` file. There is an example provided as
`login-creds.yml.example`. Simply copy this file to `login-creds.yml` and
set the values:

* `openshift_connection_server` - OpenShift Cluster API URL

* `openshift_connection_insecure_skip_tls_verify` - Whether to use TLS
  verification when connection to the cluster URL

* `openshift_connection_token` - Authentication token which can be obtained by
  running `oc whoami -t` or the token of a service account obtained with 
  `oc sa get-token -n <NAMESPACE> <SERVICE_ACCOUNT>`

Once the `logins-creds.yml` is ready you can Setup the project pipeline:

```bash
ansible-playbook pipeline-setup.yml
```

The pipeline setup creates a file called `cicd-creds.yml` which contains the
service account token of the cicd service account created for the pipeline.

Build the application with:

```bash
ansible-playbook app-build.yml
```

Promote image from build to dev:

```bash
ansible-playbook app-deploy.yml \
-e source_environment=build \
-e target_environment=dev
```

Promote image from dev to stage:

```bash
ansible-playbook app-deploy.yml \
-e source_environment=dev \
-e target_environment=stage
```

Promote image from stage to prod:

```bash
ansible-playbook app-deploy.yml \
-e source_environment=stage \
-e target_environment=prod
```

Each of these tasks can also be run with the `--check` flag to activate check
mode. When the deploy is run in check mode the source environment can be
omitted.

## pipeline-setup.yml

The pipeline setup is a provisioning job of the sort that would typically be
run by an xPaaS administrative team to build out projects for an application
environment. This example shows some of the most commonly used project features
such as creating projects with service accounts and role bindings to be used
by other processes.

In this pipeline the MySQL database is considered a static asset that is
auxilliary to the application and so part of the base environment. In a more
advanced approach the database may also be spun up and initialialized in
development projects with each deployment.

The project creation leverages OpenShift templates as a convenient way to
initialize resources with randomly generated passwords and other security
features. See the cakephp-template example for more information on template
processing.

## app-build.py

This playbook manages the OpenShift BuildConfig and then starts a build.
It is a good practice to manage an application BuildConfig along side the
application code itself so that developers can easily test containerized
builds outside of a shared platform prior to committing code.

A couple items of note in this playbook:

```yaml
  - role: openshift-provision
    openshift_resource_path:
    - resources
    openshift_clusters:
    - projects:
      - name: "{{ app_name }}-build"
        imagestreams:
        - "{{ app_name }}"
        resources:
        - app-buildconfig.yml.j2
```

The `openshift_resource_path` is a list of directories used to search for items
listed under `resources`. In this case it just points to one directory, but in
advanced cases we may have a hierarchy implemented in the search path that
allows for the same playbook to use different resource definitions depending on
the environment for the deployment or other factors.

This shows using the `imagestreams` feature, which simply creates an empty
image stream for builds to target. ImageStreams can also be created with
resource definitions when more is needed than simply a place to push from
image builds.

The resource definition referenced under `resources` ends in ".j2". This tells
openshift-provision to process the file content as a Jinja2 template and so
unlocks a wide number of powerful templating features including conditional
block and loops that are unavailable in standard OpenShift templates. The
template must produce valid YAML output. If the template returns a List of
resource definitions then each list item will be separately processed to
ensure idempotent handling.

```yaml
  - name: Build {{ app_name }}
    command: >-
      {{ oc_cmd }} start-build -F -n {{ app_name }}-build {{ app_name }}
    # Skip in check mode so it will not report changed
    when: not ansible_check_mode
```

The build is run directly from this playbook. If this were integrated in a
Jenkins job then we may want Jenkins to start the build. Since we're using
Ansible for this and supporting check mode we explicitly skip running the
build in check mode so that it won't report as a change.

## app-deploy.py

This job promotes the application image along with configuring application
level resources such as Service, Route, and DeploymentConfig. These resources
are often maintained along with application code so that developers can
throughly test running their applications in local environments and so that
these resource configurations can be versioned with the application code.

The DeploymentConfig we're using does not have a ConfigChange trigger so that
a change to both the image and the configuration does not cause two
deployments. We leave the image change trigger and then explicitly call
`oc rollout latest`, which will produce an error if a deployment is already
in progress. We catch and ignore that error message.
