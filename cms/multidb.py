import logging
import warnings

from django.conf import settings
from django.core import exceptions
from django.db import router
from django.db.models import ForeignKey
from django.db.models.deletion import CASCADE
from django.db.models.fields.related_descriptors import ReverseOneToOneDescriptor
from django.db.models.fields.reverse_related import OneToOneRel
# from django.utils.deprecation import RemovedInDjango20Warning
from django.utils.translation import ugettext_lazy as _
from django.utils.version import get_docs_version

try:
    from django.utils.deprecation import RemovedInDjango30Warning as RIDWorning
except ImportError:
    from django.utils.deprecation import  RemovedInDjango40Warning as RIDWorning


class AppRouter(object):
    """
    A router that routes data according to settings.DATABASE_APP_ROUTING.

    To use, the following must be in settings.py:
        DATABASE_APP_ROUTES = {
            'application_name': 'database_name'
        }
        DATABASE_ROUTERS = ['main.routers.AppRouter']

    Any application that is not listed in DATABASE_APP_ROUTES will be ignored
    by this router.

    See https://docs.djangoproject.com/en/1.9/topics/db/multi-db/#using-routers
    """

    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

    def db_for_read_write(self, model, **hints):
        """AppRouter-specific delegate."""
        app_label = model._meta.app_label
        self.logger.debug('routing model %s from app %s…', model, app_label)
        try:
            db = settings.DATABASE_APP_ROUTES[app_label]
            self.logger.debug('\t…routing to database %s', db)
            return db
        except KeyError:
            pass
        return None

    def db_for_read(self, model, **hints):
        """Django router function."""
        return self.db_for_read_write(model, **hints)

    def db_for_write(self, model, **hints):
        """Django router function."""
        return self.db_for_read_write(model, **hints)

    def allow_relation(self, obj1, obj2, **hints):
        """Django router function."""
        if (self.db_for_read_write(obj1, **hints) or
            self.db_for_read_write(obj2, **hints)):
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Django router function."""
        try:
            return db == settings.DATABASE_APP_ROUTES[app_label]
        except KeyError:
            pass
        return None


class RoutingForeignKey(ForeignKey):
    """
    Inherit from ForeignKey, but override db_constraint to False and use the
    ConnectionRouter to access the related object.
    """

    def __init__(self, to, on_delete=CASCADE, related_name=None, related_query_name=None,
            limit_choices_to=None, parent_link=False, to_field=None,
            db_constraint=True, **kwargs):
        db_constraint = False
        super(RoutingForeignKey, self).__init__(to, on_delete, related_name, related_query_name,
            limit_choices_to, parent_link, to_field,
            db_constraint, **kwargs)

    def validate(self, value, model_instance):
        """
        This code is verbatim from django/db/models/fields/related.py,
        except that we use self.rel.to to route the db_for_read instead of
        model_instance.__class__.
        """
        if self.remote_field.parent_link:
            return
        super(RoutingForeignKey, self).validate(value, model_instance)
        if value is None:
            return

        using = router.db_for_read(self.rel.to, instance=model_instance)
        qs = self.rel.to._default_manager.using(using).filter(
            **{self.rel.field_name: value}
        )
        qs = qs.complex_filter(self.get_limit_choices_to())
        if not qs.exists():
            raise exceptions.ValidationError(
                self.error_messages['invalid'],
                code='invalid',
                params={
                    'model': self.rel.to._meta.verbose_name, 'pk': value,
                    'field': self.rel.field_name, 'value': value,
                },  # 'pk' is included for backwards compatibility
            )


class RoutingOneToOneField(RoutingForeignKey):
    """
    This code is verbatim from django/db/models/fields/related.py,
    except that we subclass RoutingForeignKey instead of ForeignKey.
    """

    # Field flags
    many_to_many = False
    many_to_one = False
    one_to_many = False
    one_to_one = True

    related_accessor_class = ReverseOneToOneDescriptor
    rel_class = OneToOneRel

    description = _("One-to-one relationship")

    def __init__(self, to, on_delete=None, to_field=None, **kwargs):
        kwargs['unique'] = True

        if on_delete is None:
            warnings.warn(
                "on_delete will be a required arg for %s in Django 2.0. Set "
                "it to models.CASCADE on models and in existing migrations "
                "if you want to maintain the current default behavior. "
                "See https://docs.djangoproject.com/en/%s/ref/models/fields/"
                "#django.db.models.ForeignKey.on_delete" % (
                    self.__class__.__name__,
                    get_docs_version(),
                ),
                RIDWorning, 2)
            on_delete = CASCADE

        elif not callable(on_delete):
            warnings.warn(
                "The signature for {0} will change in Django 2.0. "
                "Pass to_field='{1}' as a kwarg instead of as an arg.".format(
                    self.__class__.__name__,
                    on_delete,
                ),
                RIDWorning, 2)
            to_field = on_delete
            on_delete = CASCADE  # Avoid warning in superclass

        super(RoutingOneToOneField, self).__init__(to, on_delete, to_field=to_field, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super(RoutingOneToOneField, self).deconstruct()
        if "unique" in kwargs:
            del kwargs['unique']
        return name, path, args, kwargs

    def formfield(self, **kwargs):
        if self.remote_field.parent_link:
            return None
        return super(RoutingOneToOneField, self).formfield(**kwargs)

    def save_form_data(self, instance, data):
        if isinstance(data, self.remote_field.model):
            setattr(instance, self.name, data)
        else:
            setattr(instance, self.attname, data)

    def _check_unique(self, **kwargs):
        # Override ForeignKey since check isn't applicable here.
        return []
