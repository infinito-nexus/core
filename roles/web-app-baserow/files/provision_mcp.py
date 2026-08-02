import os

from baserow.core.handler import CoreHandler
from baserow.core.mcp.models import MCPEndpoint
from baserow.core.models import UserProfile, WorkspaceUser
from django.contrib.auth import get_user_model

email = os.environ["MCP_OWNER_EMAIL"]
workspace_name = os.environ["MCP_WORKSPACE_NAME"]
endpoint_name = os.environ["MCP_ENDPOINT_NAME"]
key = os.environ["MCP_ENDPOINT_KEY"]

User = get_user_model()

owner, owner_created = User.objects.get_or_create(
    username=email,
    defaults={"email": email, "first_name": endpoint_name},
)

if owner_created:
    owner.set_unusable_password()
    owner.save()

UserProfile.objects.get_or_create(
    user=owner,
    defaults={"email_verified": True, "completed_onboarding": True},
)

membership = WorkspaceUser.objects.filter(
    user=owner, workspace__name=workspace_name
).first()

if membership is None:
    membership = CoreHandler().create_workspace(owner, name=workspace_name)

previous_key = (
    MCPEndpoint.objects.filter(
        user=owner, workspace=membership.workspace, name=endpoint_name
    )
    .values_list("key", flat=True)
    .first()
)

MCPEndpoint.objects.update_or_create(
    user=owner,
    workspace=membership.workspace,
    name=endpoint_name,
    defaults={"key": key},
)

print("CHANGED" if owner_created or previous_key != key else "UNCHANGED")
