# -*- coding: utf-8 -*-
from ..component import Component, require

from .feature import Feature, FeatureSet
from .model import Base, LayerField, LayerFieldsMixin
from .interface import (
    GEOM_TYPE,
    FIELD_TYPE,
    IFeatureLayer,
    IWritableFeatureLayer,
    IFeatureQuery,
    IFeatureQueryFilter,
    IFeatureQueryFilterBy,
    IFeatureQueryOrderBy,
    IFeatureQueryLike,
    IFeatureQueryIntersects)
from .extension import FeatureExtension


class FeatureLayerComponent(Component):
    identity = 'feature_layer'
    metadata = Base.metadata

    def initialize(self):
        self.settings['identify.attributes'] = \
            self.settings.get('identify.attributes', 'true').lower() == 'true'
        self.settings['mvt.attributes'] = \
            self.settings.get('mvt.attributes', 'false').lower() == 'true'

        self.settings['search.nominatim'] = \
            self.settings.get('search.nominatim', 'true').lower() == 'true'

        from .extension import FeatureExtension
        self.FeatureExtension = FeatureExtension

    @require('resource')
    def setup_pyramid(self, config):
        from . import view, api
        view.setup_pyramid(self, config)
        api.setup_pyramid(self, config)

    settings_info = (
        dict(key='identify.attributes', desc=u"Показывать атрибуты в идентификации"),
        dict(key='search.nominatim', desc=u"Использовать Nominatim при поиске"),
        dict(key='mvt.attributes', desc=u"Включать атрибуты в векторные тайлы"),
    )
