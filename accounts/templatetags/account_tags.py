from django import template

register = template.Library()


@register.filter
def has_role(user, role_name):
    """
    Template filter to check if a user has a specific role.
    Usage: {% if request.user|has_role:"User Manager" %}
    """
    if not user.is_authenticated:
        return False
    return user.has_role(role_name)


@register.filter
def has_group(user, group_names):
    """
    Template filter to check if a user belongs to any of the specified groups.
    Usage: {% if request.user|has_group:"System Administrator,Management" %}
    """
    if not user.is_authenticated:
        return False
    
    # Split group names by comma and strip whitespace
    groups = [name.strip() for name in group_names.split(',')]
    
    # Check if user belongs to any of the specified groups
    return user.groups.filter(name__in=groups).exists()


@register.filter
def has_perm(user, perm):
    """
    Template filter to check if a user has a specific permission.
    Usage: {% if request.user|has_perm:"app.permission" %}
    """
    if not user.is_authenticated:
        return False
    return user.has_perm(perm)
