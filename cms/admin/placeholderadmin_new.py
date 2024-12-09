# -*- coding: utf-8 -*-
import json
import uuid
import warnings

from django.conf.urls import url
from django.contrib.admin.helpers import AdminForm
from django.contrib.admin.utils import get_deleted_objects
from django.contrib.sites.shortcuts import get_current_site
from django.core.exceptions import PermissionDenied
from django.db import router, transaction
# from django.http import (
#     HttpResponse,
#     HttpResponseBadRequest,
#     HttpResponseForbidden,
#     HttpResponseNotFound,
#     HttpResponseRedirect,
# )
from django.shortcuts import get_list_or_404, get_object_or_404, render
from django.template.response import TemplateResponse
import six
from six.moves.urllib.parse import parse_qsl, urlparse
from django.utils.decorators import method_decorator
from django.utils.encoding import force_str
from django.utils import translation
from django.utils.translation import ugettext as _
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from cms import operations
from cms.admin.forms import PluginAddValidationForm
from cms.constants import PLUGIN_COPY_ACTION, PLUGIN_MOVE_ACTION, SLUG_REGEXP
from cms.exceptions import PluginLimitReached
from cms.models.placeholdermodel import Placeholder
from cms.models.placeholderpluginmodel import PlaceholderReference
from cms.models.pluginmodel import CMSPlugin
from cms.plugin_pool import plugin_pool
from cms.signals import pre_placeholder_operation, post_placeholder_operation
from cms.utils import (
    copy_plugins,
    get_cms_setting,
    get_language_from_request,
)
from cms.utils.i18n import get_language_list, get_language_code, force_language
from cms.utils.plugins import (
    requires_reload,
    has_reached_plugin_limit,
    reorder_plugins
)
from cms.utils.urlutils import admin_reverse


from django.urls import path
from django.contrib.admin.utils import NestedObjects
# from django.contrib.sites.shortcuts import get_current_site
# from django.core.exceptions import PermissionDenied
# from django.db import router, transaction
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    HttpResponseRedirect,
    JsonResponse,
)
# from django.shortcuts import get_object_or_404, render
# from django.template.response import TemplateResponse
# from django.utils.decorators import method_decorator
# from django.utils.encoding import force_str
# from django.utils.translation import gettext as _
# from django.views.decorators.clickjacking import xframe_options_sameorigin
# from django.views.decorators.http import require_POST

# from cms.models.placeholdermodel import Placeholder
# from cms.models.pluginmodel import CMSPlugin
# from cms.plugin_pool import plugin_pool
# from cms.utils import copy_plugins, get_language_from_request, reorder_plugins
# from cms.utils.plugins import has_reached_plugin_limit, requires_reload
# from cms.utils.urlutils import admin_reverse
# from cms import operations



_no_default = object()


def get_int(int_str, default=_no_default):
    """
    For convenience a get-like method for taking the int() of a string.
    :param int_str: the string to convert to integer
    :param default: an optional value to return if ValueError is raised.
    :return: the int() of «int_str» or «default» on exception.
    """
    if default == _no_default:
        return int(int_str)
    else:
        try:
            return int(int_str)
        except ValueError:
            return default


def _instance_overrides_method(base, instance, method_name):
    """
    Returns True if instance overrides a method (method_name)
    inherited from base.
    """
    bound_method = getattr(instance, method_name)
    unbound_method = getattr(base, method_name)
    return six.get_unbound_function(unbound_method) != six.get_method_function(bound_method)


class FrontendEditableAdminMixin(object):
    frontend_editable_fields = []

    def get_urls(self):
        """
        Register the url for the single field edit view
        """
        info = "%s_%s" % (self.model._meta.app_label, self.model._meta.model_name)
        pat = lambda regex, fn: url(regex, self.admin_site.admin_view(fn), name='%s_%s' % (info, fn.__name__))
        url_patterns = [
            pat(r'edit-field/(%s)/([a-z\-]+)/$' % SLUG_REGEXP, self.edit_field),
        ]
        return url_patterns + super(FrontendEditableAdminMixin, self).get_urls()

    def _get_object_for_single_field(self, object_id, language):
        # Quick and dirty way to retrieve objects for django-hvad
        # Cleaner implementation will extend this method in a child mixin
        try:
            return self.model.objects.language(language).get(pk=object_id)
        except AttributeError:
            return self.model.objects.get(pk=object_id)

    def edit_field(self, request, object_id, language):
        print('FrontendEditableAdminMixin.edit_field')
        obj = self._get_object_for_single_field(object_id, language)
        opts = obj.__class__._meta
        saved_successfully = False
        cancel_clicked = request.POST.get("_cancel", False)
        raw_fields = request.GET.get("edit_fields")
        fields = [field for field in raw_fields.split(",") if field in self.frontend_editable_fields]
        if not fields:
            context = {
                'opts': opts,
                'message': force_str(_("Field %s not found")) % raw_fields
            }
            return render(request, 'admin/cms/page/plugin/error_form.html', context)
        if not request.user.has_perm("{0}.change_{1}".format(self.model._meta.app_label,
                                                             self.model._meta.model_name)):
            context = {
                'opts': opts,
                'message': force_str(_("You do not have permission to edit this item"))
            }
            return render(request, 'admin/cms/page/plugin/error_form.html', context)
            # Dynamically creates the form class with only `field_name` field
        # enabled
        form_class = self.get_form(request, obj, fields=fields)
        if not cancel_clicked and request.method == 'POST':
            form = form_class(instance=obj, data=request.POST)
            if form.is_valid():
                form.save()
                saved_successfully = True
        else:
            form = form_class(instance=obj)
        admin_form = AdminForm(form, fieldsets=[(None, {'fields': fields})], prepopulated_fields={},
                               model_admin=self)
        media = self.media + admin_form.media
        context = {
            'CMS_MEDIA_URL': get_cms_setting('MEDIA_URL'),
            'title': opts.verbose_name,
            'plugin': None,
            'plugin_id': None,
            'adminform': admin_form,
            'add': False,
            'is_popup': True,
            'media': media,
            'opts': opts,
            'change': True,
            'save_as': False,
            'has_add_permission': False,
            'window_close_timeout': 10,
        }
        if cancel_clicked:
            # cancel button was clicked
            context.update({
                'cancel': True,
            })
            return render(request, 'admin/cms/page/plugin/confirm_form.html', context)
        if not cancel_clicked and request.method == 'POST' and saved_successfully:
            return render(request, 'admin/cms/page/plugin/confirm_form.html', context)
        return render(request, 'admin/cms/page/plugin/change_form.html', context)


class PlaceholderAdminMixin(object):

    def _get_attached_admin(self, placeholder):
        return placeholder._get_attached_admin(admin_site=self.admin_site)

    def _get_operation_language(self, request):
        # Unfortunately the ?language GET query
        # has a special meaning on the CMS.
        # It allows users to see another language while maintaining
        # the same url. This complicates language detection.
        site = get_current_site(request)
        parsed_url = urlparse(request.GET['cms_path'])
        queries = dict(parse_qsl(parsed_url.query))
        language = queries.get('language')

        if not language:
            language = translation.get_language_from_path(parsed_url.path)
        return get_language_code(language, site_id=site.pk)

    def _get_operation_origin(self, request):
        return urlparse(request.GET['cms_path']).path

    def _send_pre_placeholder_operation(self, request, operation, **kwargs):
        token = str(uuid.uuid4())

        if not request.GET.get('cms_path'):
            warnings.warn('All custom placeholder admin endpoints require '
                          'a "cms_path" GET query which points to the path '
                          'where the request originates from.'
                          'This backwards compatible shim will be removed on 3.5 '
                          'and an HttpBadRequest response will be returned instead.',
                          UserWarning)
            return token

        pre_placeholder_operation.send(
            sender=self.__class__,
            operation=operation,
            request=request,
            language=self._get_operation_language(request),
            token=token,
            origin=self._get_operation_origin(request),
            **kwargs
        )
        return token

    def _send_post_placeholder_operation(self, request, operation, token, **kwargs):
        if not request.GET.get('cms_path'):
            # No need to re-raise the warning
            return

        post_placeholder_operation.send(
            sender=self.__class__,
            operation=operation,
            request=request,
            language=self._get_operation_language(request),
            token=token,
            origin=self._get_operation_origin(request),
            **kwargs
        )

    def _get_plugin_from_id(self, plugin_id):
        queryset = CMSPlugin.objects.values_list('plugin_type', flat=True)
        plugin_type = get_list_or_404(queryset, pk=plugin_id)[0]
        # CMSPluginBase subclass
        plugin_class = plugin_pool.get_plugin(plugin_type)
        real_queryset = plugin_class.get_render_queryset().select_related('parent', 'placeholder')
        return get_object_or_404(real_queryset, pk=plugin_id)

    def get_urls(self):
        """
        Register the plugin-specific URLs (add/edit/copy/remove/move).
        """
        info = f"{self.model._meta.app_label}_{self.model._meta.model_name}"
        url_patterns = [
            path("copy-plugins/", self.admin_site.admin_view(self.copy_plugins), name=f"{info}_copy_plugins"),
            path("add-plugin/", self.admin_site.admin_view(self.add_plugin), name=f"{info}_add_plugin"),
            path("edit-plugin/<int:plugin_id>/", self.admin_site.admin_view(self.edit_plugin), name=f"{info}_edit_plugin"),
            path("delete-plugin/<int:plugin_id>/", self.admin_site.admin_view(self.delete_plugin), name=f"{info}_delete_plugin"),
            path("clear-placeholder/<int:placeholder_id>/", self.admin_site.admin_view(self.clear_placeholder), name=f"{info}_clear_placeholder"),
            path("move-plugin/", self.admin_site.admin_view(self.move_plugin), name=f"{info}_move_plugin"),
        ]
        return url_patterns + super().get_urls()

    def has_add_plugin_permission(self, request, placeholder, plugin_type):
        return placeholder.has_add_plugin_permission(request.user, plugin_type)

    def has_change_plugin_permission(self, request, plugin):
        placeholder = plugin.placeholder
        return placeholder.has_change_plugin_permission(request.user, plugin)

    def has_delete_plugin_permission(self, request, plugin):
        placeholder = plugin.placeholder
        return placeholder.has_delete_plugin_permission(request.user, plugin)

    def has_copy_plugins_permission(self, request, plugins):
        # Plugins can only be copied to the clipboard
        placeholder = request.toolbar.clipboard
        return placeholder.has_add_plugins_permission(request.user, plugins)

    def has_copy_from_clipboard_permission(self, request, placeholder, plugins):
        return placeholder.has_add_plugins_permission(request.user, plugins)

    def has_copy_from_placeholder_permission(self, request, source_placeholder, target_placeholder, plugins):
        if not source_placeholder.has_add_plugins_permission(request.user, plugins):
            return False
        return target_placeholder.has_add_plugins_permission(request.user, plugins)

    def has_move_plugin_permission(self, request, plugin, target_placeholder):
        placeholder = plugin.placeholder
        return placeholder.has_move_plugin_permission(request.user, plugin, target_placeholder)

    def has_clear_placeholder_permission(self, request, placeholder, language=None):
        if language:
            languages = [language]
        else:
            # fetch all languages this placeholder contains
            # based on it's plugins
            languages = (
                placeholder
                .cmsplugin_set
                .values_list('language', flat=True)
                .distinct()
                .order_by()
            )
        return placeholder.has_clear_permission(request.user, languages)

    def post_add_plugin(self, request, plugin):
        pass

    def post_copy_plugins(self, request, source_placeholder, target_placeholder, plugins):
        pass

    def post_edit_plugin(self, request, plugin):
        pass

    def post_move_plugin(self, request, source_placeholder, target_placeholder, plugin):
        pass

    def post_delete_plugin(self, request, plugin):
        pass

    def post_clear_placeholder(self, request, placeholder):
        pass

    def get_placeholder_template(self, request, placeholder):
        pass

    @method_decorator(require_POST)
    @xframe_options_sameorigin
    @transaction.atomic
    def add_plugin(self, request):
        """
        Adds a plugin to the placeholder.
        """
        print('PlaceholderAdminMixin.add_plugin')
        form = PluginAddValidationForm(request.GET)
        if not form.is_valid():
            error = list(form.errors.values())[0][0]
            return HttpResponseBadRequest(force_str(error))

        plugin_data = form.cleaned_data
        placeholder = plugin_data["placeholder_id"]
        plugin_type = plugin_data["plugin_type"]

        if not self.has_add_plugin_permission(request, placeholder, plugin_type):
            return HttpResponseForbidden(_("You do not have permission to add a plugin"))

        plugin_class = plugin_pool.get_plugin(plugin_type)
        plugin_instance = plugin_class(plugin_class.model, self.admin_site)

        plugin_instance._cms_initial_attributes = {
            "language": plugin_data["plugin_language"],
            "placeholder": placeholder,
            "parent": plugin_data.get("plugin_parent", None),
            "plugin_type": plugin_data["plugin_type"],
            "position": plugin_data.get("plugin_position", None),
        }

        return plugin_instance.add_view(request)


    @method_decorator(require_POST)
    @xframe_options_sameorigin
    @transaction.atomic
    def copy_plugins(self, request):
        """
        Copies plugins from one placeholder to another.
        """
        print('PlaceholderAdminMixin.copy_plugins')
        source_placeholder_id = request.POST.get("source_placeholder_id")
        target_placeholder_id = request.POST.get("target_placeholder_id")
        language = request.POST.get("plugin_language")

        source_placeholder = get_object_or_404(Placeholder, pk=source_placeholder_id)
        target_placeholder = get_object_or_404(Placeholder, pk=target_placeholder_id)

        if not self.has_copy_plugins_permission(request, source_placeholder.get_plugins_list(language)):
            return HttpResponseForbidden(_("You do not have permission to copy these plugins"))

        copy_plugins.copy_plugins_to(source_placeholder.get_plugins_list(language), target_placeholder, language)
        return JsonResponse({"success": True})

    def _copy_plugin_to_clipboard(self, request, source_placeholder, target_placeholder):
        source_language = request.POST['source_language']
        source_plugin_id = request.POST.get('source_plugin_id')
        target_language = request.POST['target_language']

        source_plugin = get_object_or_404(
            CMSPlugin,
            pk=source_plugin_id,
            language=source_language,
        )

        old_plugins = (
            CMSPlugin
            .get_tree(parent=source_plugin)
            .filter(placeholder=source_placeholder)
            .order_by('path')
        )

        if not self.has_copy_plugins_permission(request, old_plugins):
            message = _('You do not have permission to copy these plugins.')
            raise PermissionDenied(force_str(message))

        # Empty the clipboard
        target_placeholder.clear()

        copy_plugins.copy_plugins_to(
            old_plugins,
            to_placeholder=target_placeholder,
            to_language=target_language,
        )
        return old_plugins

    def _copy_placeholder_to_clipboard(self, request, source_placeholder, target_placeholder):
        source_language = request.POST['source_language']
        target_language = request.POST['target_language']

        # User is copying the whole placeholder to the clipboard.
        old_plugins = source_placeholder.get_plugins_list(language=source_language)

        if not self.has_copy_plugins_permission(request, old_plugins):
            message = _('You do not have permission to copy this placeholder.')
            raise PermissionDenied(force_str(message))

        # Empty the clipboard
        target_placeholder.clear()

        # Create a PlaceholderReference plugin which in turn
        # creates a blank placeholder called "clipboard"
        # the real clipboard has the reference placeholder inside but the plugins
        # are inside of the newly created blank clipboard.
        # This allows us to wrap all plugins in the clipboard under one plugin
        reference = PlaceholderReference.objects.create(
            name=source_placeholder.get_label(),
            plugin_type='PlaceholderPlugin',
            language=target_language,
            placeholder=target_placeholder,
        )

        copy_plugins.copy_plugins_to(
            old_plugins,
            to_placeholder=reference.placeholder_ref,
            to_language=target_language,
        )
        return old_plugins

    def _add_plugins_from_placeholder(self, request, source_placeholder, target_placeholder):
        # Plugins are being copied from a placeholder in another language
        # using the "Copy from language" placeholder operation.
        source_language = request.POST['source_language']
        target_language = request.POST['target_language']

        old_plugins = source_placeholder.get_plugins_list(language=source_language)

        # Check if the user can copy plugins from source placeholder to
        # target placeholder.
        has_permissions = self.has_copy_from_placeholder_permission(
            request,
            source_placeholder,
            target_placeholder,
            old_plugins,
        )

        if not has_permissions:
            message = _('You do not have permission to copy these plugins.')
            raise PermissionDenied(force_str(message))

        target_tree_order = target_placeholder.get_plugin_tree_order(
            language=target_language,
            parent_id=None,
        )

        operation_token = self._send_pre_placeholder_operation(
            request,
            operation=operations.ADD_PLUGINS_FROM_PLACEHOLDER,
            plugins=old_plugins,
            source_language=source_language,
            source_placeholder=source_placeholder,
            target_language=target_language,
            target_placeholder=target_placeholder,
            target_order=target_tree_order,
        )

        copied_plugins = copy_plugins.copy_plugins_to(
            old_plugins,
            to_placeholder=target_placeholder,
            to_language=target_language,
        )

        new_plugin_ids = (new.pk for new, old in copied_plugins)

        # Creates a list of PKs for the top-level plugins ordered by
        # their position.
        top_plugins = (pair for pair in copied_plugins if not pair[0].parent_id)
        top_plugins_pks = [p[0].pk for p in sorted(top_plugins, key=lambda pair: pair[1].position)]

        # All new plugins are added to the bottom
        target_tree_order = target_tree_order + top_plugins_pks

        reorder_plugins(
            target_placeholder,
            parent_id=None,
            language=target_language,
            order=target_tree_order,
        )

        new_plugins = CMSPlugin.objects.filter(pk__in=new_plugin_ids).order_by('path')

        self._send_post_placeholder_operation(
            request,
            operation=operations.ADD_PLUGINS_FROM_PLACEHOLDER,
            token=operation_token,
            plugins=list(new_plugins),
            source_language=source_language,
            source_placeholder=source_placeholder,
            target_language=target_language,
            target_placeholder=target_placeholder,
            target_order=target_tree_order,
        )
        return old_plugins

    @xframe_options_sameorigin
    def edit_plugin(self, request, plugin_id):
        """
        Edits an existing plugin.
        """
        print('PlaceholderAdminMixin.edit_plugin')
        plugin = get_object_or_404(CMSPlugin, pk=plugin_id)
        if not self.has_change_plugin_permission(request, plugin):
            return HttpResponseForbidden(_("You do not have permission to edit this plugin"))

        plugin_class = plugin_pool.get_plugin(plugin.plugin_type)
        plugin_instance = plugin_class(plugin_class.model, self.admin_site)

        response = plugin_instance.change_view(request, str(plugin_id))
        return response


    @method_decorator(require_POST)
    @xframe_options_sameorigin
    @transaction.atomic
    def move_plugin(self, request):
        """
        Moves a plugin within or across placeholders.
        """
        print('PlaceholderAdminMixin.move_plugin')
        plugin_id = request.POST.get("plugin_id")
        placeholder_id = request.POST.get("placeholder_id")
        language = request.POST.get("plugin_language")

        plugin = get_object_or_404(CMSPlugin, pk=plugin_id)
        placeholder = get_object_or_404(Placeholder, pk=placeholder_id)

        if not self.has_move_plugin_permission(request, plugin, placeholder):
            return HttpResponseForbidden(_("You do not have permission to move this plugin"))

        plugin.placeholder = placeholder
        plugin.language = language
        plugin.save()

        return JsonResponse({"success": True})


    def _paste_plugin(self, request, plugin, target_language,
                      target_placeholder, tree_order, target_parent=None):
        plugins = [plugin] + list(plugin.get_descendants())

        if not self.has_copy_from_clipboard_permission(request, target_placeholder, plugins):
            message = force_str(_("You have no permission to paste this plugin"))
            raise PermissionDenied(message)

        if target_parent:
            target_parent_id = target_parent.pk
        else:
            target_parent_id = None

        target_tree_order = [int(pk) for pk in tree_order if not pk == '__COPY__']

        action_token = self._send_pre_placeholder_operation(
            request,
            operation=operations.PASTE_PLUGIN,
            plugin=plugin,
            target_language=target_language,
            target_placeholder=target_placeholder,
            target_parent_id=target_parent_id,
            target_order=target_tree_order,
        )

        new_plugins = copy_plugins.copy_plugins_to(
            plugins,
            to_placeholder=target_placeholder,
            to_language=target_language,
            parent_plugin_id=target_parent_id,
        )

        root_plugin = new_plugins[0][0]

        # If an ordering was supplied, replace the item that has
        # been copied with the new copy
        target_tree_order.insert(tree_order.index('__COPY__'), root_plugin.pk)

        reorder_plugins(
            target_placeholder,
            parent_id=target_parent_id,
            language=target_language,
            order=target_tree_order,
        )

        # Fetch from db to update position and other tree values
        root_plugin.refresh_from_db()

        self._send_post_placeholder_operation(
            request,
            operation=operations.PASTE_PLUGIN,
            plugin=root_plugin.get_bound_plugin(),
            token=action_token,
            target_language=target_language,
            target_placeholder=target_placeholder,
            target_parent_id=target_parent_id,
            target_order=target_tree_order,
        )
        return root_plugin

    def _paste_placeholder(self, request, plugin, target_language,
                           target_placeholder, tree_order):
        plugins = plugin.placeholder_ref.get_plugins_list()

        if not self.has_copy_from_clipboard_permission(request, target_placeholder, plugins):
            message = force_str(_("You have no permission to paste this placeholder"))
            raise PermissionDenied(message)

        target_tree_order = [int(pk) for pk in tree_order if not pk == '__COPY__']

        action_token = self._send_pre_placeholder_operation(
            request,
            operation=operations.PASTE_PLACEHOLDER,
            plugins=plugins,
            target_language=target_language,
            target_placeholder=target_placeholder,
            target_order=target_tree_order,
        )

        new_plugins = copy_plugins.copy_plugins_to(
            plugins,
            to_placeholder=target_placeholder,
            to_language=target_language,
        )

        new_plugin_ids = (new.pk for new, old in new_plugins)

        # Creates a list of PKs for the top-level plugins ordered by
        # their position.
        top_plugins = (pair for pair in new_plugins if not pair[0].parent_id)
        top_plugins_pks = [p[0].pk for p in sorted(top_plugins, key=lambda pair: pair[1].position)]

        # If an ordering was supplied, we should replace the item that has
        # been copied with the new plugins
        target_tree_order[tree_order.index('__COPY__'):0] = top_plugins_pks

        reorder_plugins(
            target_placeholder,
            parent_id=None,
            language=target_language,
            order=target_tree_order,
        )

        new_plugins = list(CMSPlugin.objects.filter(pk__in=new_plugin_ids).order_by('path'))

        self._send_post_placeholder_operation(
            request,
            operation=operations.PASTE_PLACEHOLDER,
            token=action_token,
            plugins=new_plugins,
            target_language=target_language,
            target_placeholder=target_placeholder,
            target_order=target_tree_order,
        )
        return new_plugins[0]

    def _move_plugin(self, request, plugin, target_language,
                     target_placeholder, tree_order, target_parent=None):
        if not self.has_move_plugin_permission(request, plugin, target_placeholder):
            message = force_str(_("You have no permission to move this plugin"))
            raise PermissionDenied(message)

        plugin_data = {
            'language': target_language,
            'placeholder': target_placeholder,
        }

        source_language = plugin.language
        source_placeholder = plugin.placeholder
        source_tree_order = source_placeholder.get_plugin_tree_order(
            language=source_language,
            parent_id=plugin.parent_id,
        )

        if target_parent:
            target_parent_id = target_parent.pk
        else:
            target_parent_id = None

        if target_placeholder != source_placeholder:
            target_tree_order = target_placeholder.get_plugin_tree_order(
                language=target_language,
                parent_id=target_parent_id,
            )
        else:
            target_tree_order = source_tree_order

        action_token = self._send_pre_placeholder_operation(
            request,
            operation=operations.MOVE_PLUGIN,
            plugin=plugin,
            source_language=source_language,
            source_placeholder=source_placeholder,
            source_parent_id=plugin.parent_id,
            source_order=source_tree_order,
            target_language=target_language,
            target_placeholder=target_placeholder,
            target_parent_id=target_parent_id,
            target_order=target_tree_order,
        )

        if target_parent and plugin.parent != target_parent:
            # Plugin is being moved to another tree (under another parent)
            updated_plugin = plugin.update(refresh=True, parent=target_parent, **plugin_data)
            updated_plugin = updated_plugin.move(target_parent, pos='last-child')
        elif target_parent:
            # Plugin is being moved within the same tree (different position, same parent)
            updated_plugin = plugin.update(refresh=True, **plugin_data)
        else:
            # Plugin is being moved to the root (no parent)
            target = CMSPlugin.get_last_root_node()
            updated_plugin = plugin.update(refresh=True, parent=None, **plugin_data)
            updated_plugin = updated_plugin.move(target, pos='right')

        # Update all children to match the parent's
        # language and placeholder
        updated_plugin.get_descendants().update(**plugin_data)

        # Avoid query by removing the plugin being moved
        # from the source order
        new_source_order = list(source_tree_order)
        new_source_order.remove(updated_plugin.pk)

        # Reorder all plugins in the target placeholder according to the
        # passed order
        new_target_order = [int(pk) for pk in tree_order]
        reorder_plugins(
            target_placeholder,
            parent_id=target_parent_id,
            language=target_language,
            order=new_target_order,
        )

        # Refresh plugin to get new tree and position values
        updated_plugin.refresh_from_db()

        self._send_post_placeholder_operation(
            request,
            operation=operations.MOVE_PLUGIN,
            plugin=updated_plugin.get_bound_plugin(),
            token=action_token,
            source_language=source_language,
            source_placeholder=source_placeholder,
            source_parent_id=plugin.parent_id,
            source_order=new_source_order,
            target_language=target_language,
            target_placeholder=target_placeholder,
            target_parent_id=target_parent_id,
            target_order=new_target_order,
        )
        return updated_plugin

    def _cut_plugin(self, request, plugin, target_language,  target_placeholder):
        if not self.has_move_plugin_permission(request, plugin, target_placeholder):
            message = force_str(_("You have no permission to cut this plugin"))
            raise PermissionDenied(message)

        plugin_data = {
            'language': target_language,
            'placeholder': target_placeholder,
        }

        source_language = plugin.language
        source_placeholder = plugin.placeholder
        source_tree_order = source_placeholder.get_plugin_tree_order(
            language=source_language,
            parent_id=plugin.parent_id,
        )

        action_token = self._send_pre_placeholder_operation(
            request,
            operation=operations.CUT_PLUGIN,
            plugin=plugin,
            clipboard=target_placeholder,
            clipboard_language=target_language,
            source_language=source_language,
            source_placeholder=source_placeholder,
            source_parent_id=plugin.parent_id,
            source_order=source_tree_order,
        )

        # Empty the clipboard
        target_placeholder.clear()

        target = CMSPlugin.get_last_root_node()
        updated_plugin = plugin.update(refresh=True, parent=None, **plugin_data)
        updated_plugin = updated_plugin.move(target, pos='right')

        # Update all children to match the parent's
        # language and placeholder (clipboard)
        updated_plugin.get_descendants().update(**plugin_data)

        # Avoid query by removing the plugin being moved
        # from the source order
        new_source_order = list(source_tree_order)
        new_source_order.remove(updated_plugin.pk)

        self._send_post_placeholder_operation(
            request,
            operation=operations.CUT_PLUGIN,
            token=action_token,
            plugin=updated_plugin.get_bound_plugin(),
            clipboard=target_placeholder,
            clipboard_language=target_language,
            source_language=source_language,
            source_placeholder=source_placeholder,
            source_parent_id=plugin.parent_id,
            source_order=new_source_order,
        )
        return updated_plugin

    @method_decorator(require_POST)
    @xframe_options_sameorigin
    @transaction.atomic
    def delete_plugin(self, request, plugin_id):
        """
        Deletes an existing plugin.
        """
        print('PlaceholderAdminMixin.delete_plugin')
        plugin = get_object_or_404(CMSPlugin, pk=plugin_id)
        if not self.has_delete_plugin_permission(request, plugin):
            return HttpResponseForbidden(_("You do not have permission to delete this plugin"))

        opts = plugin._meta
        using = router.db_for_write(opts.model)
        collector = NestedObjects(using)
        collector.collect([plugin])

        deleted_objects = collector.nested()
        protected = collector.protected

        if request.method == "POST":
            if protected:
                return HttpResponseForbidden(_("You cannot delete protected objects"))

            plugin.delete()
            self.log_deletion(request, plugin, force_str(plugin))
            self.message_user(request, _('The plugin "%s" was deleted successfully.') % plugin)
            return HttpResponseRedirect(admin_reverse("index", current_app=self.admin_site.name))

        context = {
            "title": _("Are you sure?"),
            "object_name": _("plugin"),
            "object": plugin,
            "deleted_objects": deleted_objects,
            "protected": protected,
            "opts": opts,
            "app_label": opts.app_label,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/cms/page/plugin/delete_confirmation.html", context)


    @xframe_options_sameorigin
    def clear_placeholder(self, request, placeholder_id):
        print('PlaceholderAdminMixin.clear_placeholder')
        placeholder = get_object_or_404(Placeholder, pk=placeholder_id)
        language = request.GET.get('language')

        if placeholder.pk == request.toolbar.clipboard.pk:
            # Clear the clipboard without permission checks
            placeholder.clear(language)
            return HttpResponseRedirect(admin_reverse('index', current_app=self.admin_site.name))

        if not self.has_clear_placeholder_permission(request, placeholder, language):
            return HttpResponseForbidden(_("You do not have permission to clear this placeholder"))

        opts = Placeholder._meta
        using = router.db_for_write(Placeholder)
        plugins = placeholder.get_plugins_list(language)

        # Updated for Django 3.2 compatibility
        collector = self.admin_site.get_deleted_objects(plugins, request, using)
        deleted_objects, model_count, perms_needed, protected = collector

        obj_display = force_str(placeholder)

        if request.POST:
            # User has confirmed the deletion
            if perms_needed:
                return HttpResponseForbidden(_("You do not have permission to clear this placeholder"))

            operation_token = self._send_pre_placeholder_operation(
                request,
                operation=operations.CLEAR_PLACEHOLDER,
                plugins=plugins,
                placeholder=placeholder,
            )

            placeholder.clear(language)
            placeholder.mark_as_dirty(language, clear_cache=True)

            self.log_deletion(request, placeholder, obj_display)
            self.message_user(request, _('The placeholder "%(obj)s" was cleared successfully.') % {'obj': obj_display})

            self._send_post_placeholder_operation(
                request,
                operation=operations.CLEAR_PLACEHOLDER,
                token=operation_token,
                plugins=plugins,
                placeholder=placeholder,
            )

            uses_hook = _instance_overrides_method(PlaceholderAdminMixin, self, 'post_clear_placeholder')

            if uses_hook:
                warnings.warn('The post_clear_placeholder hook has been deprecated. '
                            'Please use placeholder operation signals instead.',
                            DeprecationWarning)
                self.post_clear_placeholder(request, placeholder)

            return HttpResponseRedirect(admin_reverse('index', current_app=self.admin_site.name))

        # Prepare the confirmation context
        if perms_needed or protected:
            title = _("Cannot delete %(name)s") % {"name": obj_display}
        else:
            title = _("Are you sure?")

        context = {
            "title": title,
            "object_name": _("placeholder"),
            "object": placeholder,
            "deleted_objects": deleted_objects,
            "perms_lacking": perms_needed,
            "protected": protected,
            "opts": opts,
            "app_label": opts.app_label,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/cms/page/plugin/delete_confirmation.html", context)
