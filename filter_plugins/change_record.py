import json
import re

def record_change_command(value, change_record=''):
    if change_record:
        fh = open(change_record, 'a')
        cmd = [
            item for item in value['cmd']
            if not item.startswith('--server=')
            and not item.startswith('--token=')
        ]
        if cmd[0] == 'echo':
            cmd.pop(0)
        fh.write(
            "---\n"
            "action: command\n" +
            'command: ' + json.dumps(cmd) + "\n"
        )
    return True

def record_change_provision(value, change_record=''):
    if not value['changed']:
        return False
    if not change_record:
        return True
    fh = open(change_record, 'a')
    fh.write("---\n")
    fh.write('action: ' + value['action'] + "\n")
    fh.write('kind: ' + value['resource']['kind'] + "\n")
    fh.write('name: ' + value['resource']['metadata']['name'] + "\n")
    if 'namespace' in value['resource']['metadata']:
        fh.write('namespace: ' + value['resource']['metadata']['namespace'] + "\n")
    if value.get('patch', None):
        fh.write('patch: ' + json.dumps(value['patch']) + "\n")
    else:
        fh.write('resource: ' + json.dumps(value['resource']) + "\n")
    return True

class FilterModule(object):
    '''
    custom jinja2 filters for working with collections
    '''

    def filters(self):
        return {
            'record_change_command': record_change_command,
            'record_change_provision': record_change_provision
        }
