# -*- coding: utf-8 -*-
import operator
from sqlalchemy.engine.url import (
    URL as EngineURL,
    make_url as make_engine_url)
from zope.interface import implements

from .. import db
from ..models import declarative_base
from ..resource import (
    Resource,
    ConnectionScope,
    DataStructureScope,
    DataScope,
    Serializer,
    SerializedProperty as SP,
    SerializedRelationship as SR,
    SerializedResourceRelationship as SRR,
    ResourceError,
    Forbidden)
from ..env import env
from ..geometry import geom_from_wkt, box
from ..layer import SpatialLayerMixin
from ..feature_layer import (
    Feature,
    FeatureSet,
    LayerField,
    LayerFieldsMixin,
    GEOM_TYPE,
    FIELD_TYPE,
    IFeatureLayer,
    IFeatureQuery,
    IFeatureQueryFilter,
    IFeatureQueryFilterBy,
    IFeatureQueryLike,
    IFeatureQueryIntersects)

Base = declarative_base()


GEOM_TYPE_DISPLAY = (u"Точка", u"Линия", u"Полигон")

PC_READ = ConnectionScope.read
PC_WRITE = ConnectionScope.write
PC_CONNECT = ConnectionScope.connect


class PostgisConnection(Base, Resource):
    identity = 'postgis_connection'
    cls_display_name = u"Соединение PostGIS"

    __scope__ = ConnectionScope

    hostname = db.Column(db.Unicode, nullable=False)
    database = db.Column(db.Unicode, nullable=False)
    username = db.Column(db.Unicode, nullable=False)
    password = db.Column(db.Unicode, nullable=False)

    @classmethod
    def check_parent(self, parent):
        return parent.cls == 'resource_group'

    def get_engine(self):
        comp = env.postgis

        # На случай, если параметры подключения изменинись
        # их нужно проверять при каждом запросе подключения
        credhash = (self.hostname, self.database, self.username, self.password)

        if self.id in comp._engine:
            engine = comp._engine[self.id]

            if engine._credhash == credhash:
                return engine

            else:
                del comp._engine[self.id]

        engine = db.create_engine(make_engine_url(EngineURL(
            'postgresql+psycopg2',
            host=self.hostname, database=self.database,
            username=self.username, password=self.password)))

        engine._credhash = credhash

        comp._engine[self.id] = engine
        return engine

    def get_connection(self):
        return self.get_engine().connect()


class PostgisConnectionSerializer(Serializer):
    identity = PostgisConnection.identity
    resclass = PostgisConnection

    hostname = SP(read=PC_READ, write=PC_WRITE)
    database = SP(read=PC_READ, write=PC_WRITE)
    username = SP(read=PC_READ, write=PC_WRITE)
    password = SP(read=PC_READ, write=PC_WRITE)


class PostgisLayerField(Base, LayerField):
    identity = 'postgis_layer'

    __tablename__ = LayerField.__tablename__ + '_' + identity
    __mapper_args__ = dict(polymorphic_identity=identity)

    id = db.Column(db.ForeignKey(LayerField.id), primary_key=True)
    column_name = db.Column(db.Unicode, nullable=False)


class PostgisLayer(Base, Resource, SpatialLayerMixin, LayerFieldsMixin):
    identity = 'postgis_layer'
    cls_display_name = u"Слой PostGIS"

    __scope__ = DataScope

    implements(IFeatureLayer)

    connection_id = db.Column(db.ForeignKey(Resource.id), nullable=False)
    schema = db.Column(db.Unicode, default=u'public', nullable=False)
    table = db.Column(db.Unicode, nullable=False)
    column_id = db.Column(db.Unicode, nullable=False)
    column_geom = db.Column(db.Unicode, nullable=False)
    geometry_type = db.Column(db.Enum(*GEOM_TYPE.enum), nullable=False)
    geometry_srid = db.Column(db.Integer, nullable=False)

    __field_class__ = PostgisLayerField

    connection = db.relationship(
        Resource,
        foreign_keys=connection_id,
        cascade=False, cascade_backrefs=False)

    @classmethod
    def check_parent(self, parent):
        return parent.cls == 'resource_group'

    def get_info(self):
        return super(PostgisLayer, self).get_info() + (
            (u"Тип геометрии", dict(zip(GEOM_TYPE.enum, GEOM_TYPE_DISPLAY))[
                self.geometry_type]),
            (u"Подключение", self.connection),
            (u"Схема", self.schema),
            (u"Таблица", self.table),
            (u"Поле ID", self.column_id),
            (u"Поле геометрии", self.column_geom),
        )

    @property
    def source(self):
        source_meta = super(PostgisLayer, self).source
        source_meta.update(dict(
            schema=self.schema,
            table=self.table,
            column_id=self.column_id,
            column_geom=self.column_geom,
            geometry_type=self.geometry_type)
        )
        return source_meta

    def setup(self):
        fdata = dict()
        for f in self.fields:
            fdata[f.keyname] = dict(
                display_name=f.display_name,
                grid_visibility=f.grid_visibility)

        for f in list(self.fields):
            self.fields.remove(f)

        self.feature_label_field = None

        conn = self.connection.get_connection()

        try:
            result = conn.execute(
                """SELECT type, srid FROM geometry_columns
                WHERE f_table_schema = %s
                    AND f_table_name = %s
                    AND f_geometry_column = %s""",
                self.schema,
                self.table,
                self.column_geom
            )

            row = result.first()
            if row:
                self.geometry_srid = row['srid']

                table_geometry_type = row['type'].replace('MULTI', '')

                # Если тип геометрии не указан в базе,
                # то он должен быть указан заранее
                assert not (
                    table_geometry_type == 'GEOMETRY'
                    and self.geometry_type is None
                )

                # Если тип геометрии указан в базе,
                # то заранее не должен быть указан другой
                assert not (
                    self.geometry_type is not None
                    and table_geometry_type != 'GEOMETRY'
                    and self.geometry_type != table_geometry_type
                )

                if self.geometry_type is None:
                    self.geometry_type = table_geometry_type

            result = conn.execute(
                """SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s
                    AND table_name = %s
                ORDER BY ordinal_position""",
                self.schema,
                self.table
            )
            for row in result:
                if row['column_name'] == self.column_id:
                    assert row['data_type'] == 'integer'
                elif row['column_name'] == self.column_geom:
                    pass
                elif row['column_name'] in ('id', 'geom'):
                    # FIXME: На данный момент наличие полей id или
                    # geom полностью ломает векторный слой
                    pass
                else:
                    datatype = None
                    if row['data_type'] == 'integer':
                        datatype = FIELD_TYPE.INTEGER
                    elif row['data_type'] == 'double precision':
                        datatype = FIELD_TYPE.REAL
                    elif row['data_type'] == 'character varying':
                        datatype = FIELD_TYPE.STRING
                    elif row['data_type'] == 'uuid':
                        datatype = FIELD_TYPE.STRING
                    elif row['data_type'] == 'date':
                        datatype = FIELD_TYPE.STRING

                    if datatype is not None:
                        fopts = dict(display_name=row['column_name'])
                        fopts.update(fdata.get(row['column_name'], dict()))
                        self.fields.append(PostgisLayerField(
                            keyname=row['column_name'],
                            datatype=datatype,
                            column_name=row['column_name'],
                            **fopts))
        finally:
            conn.close()

    # IFeatureLayer

    @property
    def feature_query(self):

        class BoundFeatureQuery(FeatureQueryBase):
            layer = self

        return BoundFeatureQuery

    def field_by_keyname(self, keyname):
        for f in self.fields:
            if f.keyname == keyname:
                return f

        raise KeyError("Field '%s' not found!" % keyname)


DataScope.read.require(
    ConnectionScope.connect,
    attr='connection', cls=PostgisLayer)


class _fields_action(SP):
    """ Специальный write-only атрибут, обеспечивающий обновление
    списка полей с сервера """

    def setter(self, srlzr, value):
        if value == 'update':
            if srlzr.obj.connection.has_permission(PC_CONNECT, srlzr.user):
                srlzr.obj.setup()
            else:
                raise Forbidden()
        elif value != 'keep':
            raise ResourceError()


class PostgisLayerSerializer(Serializer):
    identity = PostgisLayer.identity
    resclass = PostgisLayer

    __defaults = dict(read=DataStructureScope.read,
                      write=DataStructureScope.write)

    connection = SRR(**__defaults)

    schema = SP(**__defaults)
    table = SP(**__defaults)
    column_id = SP(**__defaults)
    column_geom = SP(**__defaults)

    geometry_type = SP(**__defaults)
    geometry_srid = SP(**__defaults)

    srs = SR(**__defaults)

    fields = _fields_action(write=DataStructureScope.write)


class FeatureQueryBase(object):
    implements(
        IFeatureQuery,
        IFeatureQueryFilter,
        IFeatureQueryFilterBy,
        IFeatureQueryLike,
        IFeatureQueryIntersects)

    def __init__(self):
        self._geom = None
        self._box = None

        self._fields = None
        self._limit = None
        self._offset = None

        self._filter = None
        self._filter_by = None
        self._like = None
        self._intersects = None

    def geom(self):
        self._geom = True

    def box(self):
        self._box = True

    def fields(self, *args):
        self._fields = args

    def limit(self, limit, offset=0):
        self._limit = limit
        self._offset = offset

    def filter(self, *args):
        self._filter = args

    def filter_by(self, **kwargs):
        self._filter_by = kwargs

    def order_by(self, *args):
        self._order_by = args

    def like(self, value):
        self._like = value

    def intersects(self, geom):
        self._intersects = geom

    def __call__(self):
        tab = db.sql.table(self.layer.table)
        tab.schema = self.layer.schema

        tab.quote = True
        tab.quote_schema = True

        select = db.select([], tab)

        def addcol(col):
            select.append_column(col)

        idcol = db.sql.column(self.layer.column_id)
        addcol(idcol.label('id'))

        geomcol = db.sql.column(self.layer.column_geom)
        geomexpr = db.func.st_transform(geomcol, self.layer.srs_id)

        if self._geom:
            addcol(db.func.st_astext(geomexpr).label('geom'))

        fieldmap = []
        for idx, fld in enumerate(self.layer.fields, start=1):
            if not self._fields or fld.keyname in self._fields:
                clabel = 'f%d' % idx
                addcol(db.sql.column(fld.column_name).label(clabel))
                fieldmap.append((fld.keyname, clabel))

        if self._filter_by:
            for k, v in self._filter_by.iteritems():
                if k == 'id':
                    select.append_whereclause(idcol == v)
                else:
                    select.append_whereclause(db.sql.column(k) == v)

        if self._filter:
            l = []
            for k, o, v in self._filter:
                op = getattr(operator, o)
                if k == 'id':
                    l.append(op(idcol, v))
                else:
                    l.append(op(db.sql.column(k), v))

            select.append_whereclause(db.and_(*l))

        if self._like:
            l = []
            for fld in self.layer.fields:
                if fld.datatype == FIELD_TYPE.STRING:
                    l.append(db.sql.cast(
                        db.sql.column(fld.column_name),
                        db.Unicode).ilike(
                        '%' + self._like + '%'))

            select.append_whereclause(db.or_(*l))

        if self._intersects:
            intgeom = db.func.st_setsrid(db.func.st_geomfromtext(
                self._intersects.wkt), self._intersects.srid)
            select.append_whereclause(db.func.st_intersects(
                geomcol, db.func.st_transform(
                    intgeom, self.layer.geometry_srid)))

        if self._box:
            addcol(db.func.st_xmin(geomexpr).label('box_left'))
            addcol(db.func.st_ymin(geomexpr).label('box_bottom'))
            addcol(db.func.st_xmax(geomexpr).label('box_right'))
            addcol(db.func.st_ymax(geomexpr).label('box_top'))

        gt = self.layer.geometry_type
        select.append_whereclause(db.func.geometrytype(db.sql.column(
            self.layer.column_geom)).in_((gt, 'MULTI' + gt)))

        select.append_order_by(idcol)

        class QueryFeatureSet(FeatureSet):
            layer = self.layer

            _geom = self._geom
            _box = self._box
            _fields = self._fields
            _limit = self._limit
            _offset = self._offset

            def __iter__(self):
                if self._limit:
                    query = select.limit(self._limit).offset(self._offset)
                else:
                    query = select

                conn = self.layer.connection.get_connection()

                try:
                    for row in conn.execute(query):
                        fdict = dict([(k, row[l]) for k, l in fieldmap])

                        if self._geom:
                            geom = geom_from_wkt(row['geom'])
                        else:
                            geom = None

                        yield Feature(
                            layer=self.layer, id=row['id'],
                            fields=fdict, geom=geom,
                            box=box(
                                row['box_left'], row['box_bottom'],
                                row['box_right'], row['box_top']
                            ) if self._box else None
                        )

                finally:
                    conn.close()

            @property
            def total_count(self):
                conn = self.layer.connection.get_connection()

                try:
                    result = conn.execute(db.select(
                        [db.sql.text('COUNT(id)'), ],
                        from_obj=select.alias('all')))
                    for row in result:
                        return row[0]
                finally:
                    conn.close()

        return QueryFeatureSet()
