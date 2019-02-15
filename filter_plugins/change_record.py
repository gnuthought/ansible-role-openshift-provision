import re
import yaml

def is_connection_opt(s):
    m = re.match(r'--([a-z-]+)=', s)
    return m and m.group(1) in (
        'as',
        'as-group',
	'certificate-authority',
        'client-certificate',
        'client-key',
        'cluster',
        'config',
        'context',
        'insecure-skip-tls-verify',
        'kubeconfig',
        'match-server-version',
        'request-timeout',
        'server',
        'token',
        'user'
    )

def format_change_command(value):
    cmd = [
        item for item in value['cmd']
        if not is_connection_opt(item)
    ]
    if cmd[0] == 'echo':
        cmd.pop(0)
    return {
        'action': 'command',
        'command': cmd
    }

def format_change_provision(value):
    kind = value['resource']['kind']
    change = {
        'action': value['action'],
        'kind': kind,
        'name': value['resource']['metadata']['name']
    }
    if 'namespace' in value['resource']['metadata']:
        change['namespace'] = value['resource']['metadata']['namespace']
    if kind != 'Secret':
        if value.get('patch', None):
            change['patch'] = value['patch']
        else:
            change['resource'] = value['resource']
    return change

def record_change(change, change_record):
    fh = open(change_record, 'a')
    yaml.safe_dump(
        change,
        fh,
        default_flow_style=False,
        explicit_start=True
    )

def record_change_command(value, change_record=''):
    if change_record:
        record_change(
            format_change_command(value),
            change_record
        )
    return True


def record_change_provision(value, change_record=''):
    if value['changed'] and change_record:
        record_change(
            format_change_provision(value),
            change_record
        )
    return value['changed']

class FilterModule(object):
    '''
    custom jinja2 filters for working with collections
    '''

    def filters(self):
        return {
            'record_change_command': record_change_command,
            'record_change_provision': record_change_provision
        }
