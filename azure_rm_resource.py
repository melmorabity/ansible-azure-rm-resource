#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright © 2016-2018 Mohamed El Morabity
#
# This program is free software: you can redistribute it and/or modify it under the terms of the GNU
# General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
# even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program. If not,
# see <http://www.gnu.org/licenses/>.


from ansible.module_utils.azure_rm_common import AzureRMModuleBase


DOCUMENTATION = '''
---
module: azure_rm_resource
author: Mohamed El Morabity
short_description: Manage Azure resources.
description:
  - Create, update or delete an Azure resource.
options:
  resource_group:
    description:
      - Name of resource group.
    type: string
    required: True
  provider_namespace:
    description:
      - Resource provider namespace.
    type: string
    required: True
  parent_resource_path:
    description:
      - Parent resource path.
    type: string
    required: False
  resource_type:
    description:
      - Resource type.
    type: string
    required: True
  name:
    description:
      - Name of the resource.
    required: true
  location:
    description:
      - Valid Azure location. Defaults to location of the resource group.
    default: resource_group location
    type: string
    required: False
  tags:
    description:
      - Dictionary of string:string pairs to assign as metadata to the object. Metadata tags on the object will be updated with any provided values.
    type: dict
    required: False
  plan:
    description:
      - Plan of the resource.
    type: dict
    required: False
  properties:
    description:
      - Resource properties.
    type: dict
    required: False
  kind:
    description:
      - Kind of the resource.
    type: string
    required: False
  managed_by:
    description:
      - ID of the resource that manages this resource.
    type: string
    required: False
  sku:
    description:
      - Sku of the resource.
    type: dict
    required: False
  identity:
    description:
      - Identity of the resource.
    type: dict
    required: False
  state:
    description:
      - Assert the state of the resource.
    type: string
    choices:
      - present
      - absent
    required: False
    default: present
  update:
    description:
      - Use to control if resource parameters must be updated if the resource exists.
      - If enabled, the resource will be updated with specified parameters.
    type: boolean
    required: false
    default: true

extends_documentation_fragment:
    - azure
    - azure_tags
'''

EXAMPLES = '''
# Note: None of these examples set subscription_id, client_id, client_secret and
# tenant_id. It is assumed that their matching environment variables are set.

# Add tags to an existing virtual machine and change its size
- local_action:
    module: azure_rm_resource
    resource_group: my_resoure_group
    provider_namespace: Microsoft.Compute
    type: virtualMachines
    name: my_virtual_machine
    tags:
      key: value
    properties:
      hardwareProfile:
        vmSize: Standard_D2_v2

# Delete a virtual machine
- local_action:
    module: azure_rm_resource
    resource_group: my_resoure_group
    provider_namespace: Microsoft.Compute
    type: virtualMachines
    name: my_virtual_machine
    state: absent
'''


try:
    from azure.mgmt.resource.resources.models import GenericResource, Identity, Plan, Sku
    from msrest.exceptions import ClientRequestError
    from msrestazure.azure_exceptions import CloudError
except ImportError:
    # This is handled in azure_rm_common
    pass


AZURE_OBJECT_CLASS = 'GenericResource'

class AzureRMResource(AzureRMModuleBase):
    def __init__(self):
        self.module_arg_spec = {
            'resource_group': {'type': 'str', 'required': True},
            'provider_namespace': {'type': 'str', 'required': True},
            'parent_resource_path': {'type': 'str'},
            'resource_type': {'type': 'str', 'required': True},
            'name': {'type': 'str', 'required': True},
            'location': {'type': 'str'},
            'plan': {'type': 'dict'},
            'properties': {'type': 'dict'},
            'kind': {'type': 'str'},
            'managed_by': {'type': 'str'},
            'sku': {'type': 'dict'},
            'identity': {'type': 'dict'},
            'api_version': {'type': 'str'},
            'state': {'type': 'str', 'default': 'present', 'choices': ['present', 'absent']},
            'update': {'type': 'bool', 'default': True}
        }

        self.resource_group = None
        self.provider_namespace = None
        self.parent_resource_path = None
        self.resource_type = None
        self.name = None
        self.location = None
        self.tags = None
        self.plan = None
        self.properties = None
        self.kind = None
        self.managed_by = None
        self.sku = None
        self.identity = None
        self.api_version = None
        self.resource_group = None
        self.state = None
        self.update = None

        self.results = dict(changed=False, state=dict(), ansible_facts=dict(azure_resource=None))

        super(AzureRMResource, self).__init__(self.module_arg_spec, supports_check_mode=True)

    # Taken from azure-cli (https://github.com/Azure/azure-cli/), under MIT license
    def resolve_api_version(self):
        """Resolve API version for a given resource type."""

        provider = self.rm_client.providers.get(self.provider_namespace)

        # If available, we will use parent resource's api-version
        if self.parent_resource_path:
            resource_type = self.parent_resource_path.split('/')[0]
        else:
            resource_type = self.resource_type

        resource_type_objects = [rt for rt in provider.resource_types
                                 if rt.resource_type.lower() == self.resource_type.lower()]
        if not resource_type_objects:
            self.fail('Resource type {} not found'.format(resource_type))
        if len(resource_type_objects) == 1 and resource_type_objects[0].api_versions:
            # Consider stable versions only. If no stable version available, return the first one
            api_versions = [v for v in resource_type_objects[0].api_versions
                            if 'preview' not in v.lower()]
            return api_versions[0] if api_versions else resource_type_objects[0].api_versions[0]
        else:
            self.fail('API version is required and could not be resolved for '
                      'resource {}'.format(resource_type))

    @staticmethod
    def _dict_string_values(obj):
        """Return the specified dictionary with all its "primitive" values converted to string."""

        if isinstance(obj, dict):
            return dict([(key, AzureRMResource._dict_string_values(value)) \
                         for key, value in obj.items()])
        if isinstance(obj, list):
            return map(AzureRMResource._dict_string_values, obj)

        return str(obj) if obj is not None else obj

    def _check_resource_changed(self, resource):
        """Check whether module resource parameters update current resource parameters."""

        resource_changed = dict(resource)
        changed = False

        for field in 'location', 'kind', 'managed_by':
            if getattr(self, field) and resource.get(field, '').lower() != self.location.lower():
                resource_changed[field] = getattr(self, field)
                changed = True

        for field in 'plan', 'properties', 'sku', 'identity':
            # Use string values to compare dictionaries, to avoid "false" differences due to
            # number/string comparisons
            parameter = self._dict_string_values(resource.get(field) or {})
            parameter_after = dict(parameter)
            parameter_after.update(self._dict_string_values(getattr(self, field) or {}))
            if parameter != parameter_after:
                resource_changed[field] = getattr(self, field)
                changed = True

        return (changed, resource_changed)

    def _create_or_update_resource(self, resource_object):
        """Create or update a resource with specified parameters."""

        try:
            poller = self.rm_client.resources.create_or_update(
                self.resource_group, self.provider_namespace, self.parent_resource_path,
                self.resource_type, self.name, self.api_version, parameters=resource_object
            )
            result = self.get_poller_result(poller)
        except CloudError as ex:
            self.fail('Failed to create or update resource {}: {}'.format(self.name, ex))

        return self.serialize_obj(result, AZURE_OBJECT_CLASS)

    def _delete_resource(self):
        """Delete an Azure resource."""

        try:
            poller = self.rm_client.resources.delete(
                self.resource_group, self.provider_namespace, self.parent_resource_path,
                self.resource_type, self.name, self.api_version
            )
            self.get_poller_result(poller)
        except CloudError as ex:
            self.fail('Deleting resource {} failed: {}'.format(self.name, ex))

    def exec_module(self, **kwargs):
        for key in list(self.module_arg_spec.keys()) + ['tags', 'append_tags']:
            setattr(self, key, kwargs[key])

        self.results['check_mode'] = self.check_mode

        resource_group = self.get_resource_group(self.resource_group)
        if not self.location:
            # Set default location
            self.location = resource_group.location

        if not self.parent_resource_path:
            self.parent_resource_path = ''

        if not self.api_version:
            self.api_version = self.resolve_api_version()

        changed = False
        results = dict()
        resource = None

        try:
            self.log('Fetching resource {}'.format(self.name))
            resource = self.rm_client.resources.get(self.resource_group, self.provider_namespace,
                                                    self.parent_resource_path,
                                                    self.resource_type, self.name, self.api_version)
            results = self.serialize_obj(resource, AZURE_OBJECT_CLASS)
            self.check_provisioning_state(resource, self.state)

            self.results['state'] = results

            if self.state == 'present' and self.update:
                changed, self.results['state'] = self._check_resource_changed(results)
                update_tags, self.results['state']['tags'] = self.update_tags(results.get('tags'))
                if update_tags:
                    changed = True
            else:
                changed = True
        except ClientRequestError as ex:
            # Workaroung for some failing API calls for non-existing resources (e.g. RecoveryVault
            # backup items, amongst others)
            if ex.message == 'too many 500 error responses':
                # Resource doesn't exist
                pass
        except CloudError:
            changed = self.state == 'present'

        self.results['changed'] = changed

        if self.check_mode:
            return self.results

        if changed:
            if self.state == 'present':
                plan_object = None if not self.results['state'].get('plan') \
                              else Plan(self.results['state']['plan'])
                sku_object = None if not self.results['state'].get('sku') \
                              else Sku(self.results['state']['sku'])
                identity_object = None if not self.results['state'].get('identity') \
                              else Identity(self.results['state']['identity'])
                resource_object = GenericResource(
                    location=self.results['state'].get('location'),
                    tags=self.results['state'].get('tags'),
                    plan=plan_object, properties=self.results['state'].get('properties'),
                    kind=self.results['state'].get('kind'),
                    managed_by=self.results['state'].get('managed_by'), sku=sku_object,
                    identity=identity_object
                )
                self.results['state'] = self._create_or_update_resource(resource_object)
            elif self.state == 'absent':
                self._delete_resource()

        return self.results


def main():
    AzureRMResource()


if __name__ == '__main__':
    main()
