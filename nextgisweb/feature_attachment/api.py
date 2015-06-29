# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from StringIO import StringIO
import json

from PIL import Image
from pyramid.response import Response, FileResponse

from ..resource import DataScope, resource_factory
from ..env import env
from ..models import DBSession

from .model import FeatureAttachment


def download(resource, request):
    request.resource_permission(DataScope.read)

    obj = FeatureAttachment.filter_by(
        id=request.matchdict['aid'], resource_id=resource.id,
        feature_id=request.matchdict['fid']
    ).one()

    fn = env.file_storage.filename(obj.fileobj)
    return FileResponse(fn, content_type=bytes(obj.mime_type), request=request)


def image(resource, request):
    request.resource_permission(DataScope.read)

    obj = FeatureAttachment.filter_by(
        id=request.matchdict['aid'], resource_id=resource.id,
        feature_id=request.matchdict['fid']
    ).one()

    image = Image.open(env.file_storage.filename(obj.fileobj))

    if 'size' in request.GET:
        image.thumbnail(
            map(int, request.GET['size'].split('x')),
            Image.ANTIALIAS)

    buf = StringIO()
    image.save(buf, 'jpeg')
    buf.seek(0)

    return Response(body_file=buf, content_type=b'image/jpeg')


def iget(resource, request):
    request.resource_permission(DataScope.read)

    obj = FeatureAttachment.filter_by(
        id=request.matchdict['aid'], resource_id=resource.id,
        feature_id=request.matchdict['fid']
    ).one()

    return Response(
        json.dumps(obj.serialize()),
        content_type=b'application/json')


def idelete(resource, request):
    request.resource_permission(DataScope.read)

    obj = FeatureAttachment.filter_by(
        id=request.matchdict['aid'], resource_id=resource.id,
        feature_id=request.matchdict['fid']
    ).one()

    DBSession.delete(obj)

    return Response(
        json.dumps(None),
        content_type=b'application/json')


def iput(resource, request):
    request.resource_permission(DataScope.write)

    obj = FeatureAttachment.filter_by(
        id=request.matchdict['aid'], resource_id=resource.id,
        feature_id=request.matchdict['fid']
    ).one()

    obj.deserialize(request.json_body)

    DBSession.flush()

    return Response(
        json.dumps(dict(id=obj.id)),
        content_type=b'application/json')


def cget(resource, request):
    request.resource_permission(DataScope.read)

    query = FeatureAttachment.filter_by(
        feature_id=request.matchdict['fid'],
        resource_id=resource.id)

    result = map(lambda itm: itm.serialize(), query)

    return Response(
        json.dumps(result),
        content_type=b'application/json')


def cpost(resource, request):
    request.resource_permission(DataScope.write)

    query = resource.feature_query()
    query.filter_by(id=request.matchdict['fid'])
    query.limit(1)

    feature = None
    for f in query():
        feature = f

    obj = FeatureAttachment(resource_id=feature.layer.id, feature_id=feature.id)
    obj.deserialize(request.json_body)

    DBSession.add(obj)
    DBSession.flush()

    return Response(
        json.dumps(dict(id=obj.id)),
        content_type=b'application/json')


def setup_pyramid(comp, config):
    colurl = '/api/resource/{id}/feature/{fid}/attachment/'
    itmurl = '/api/resource/{id}/feature/{fid}/attachment/{aid}'

    config.add_route(
        'feature_attachment.download',
        itmurl + '/download',
        client=('id', 'fid', 'aid'),
        factory=resource_factory) \
        .add_view(download)

    config.add_route(
        'feature_attachment.image',
        itmurl + '/image',
        client=('id', 'fid', 'aid'),
        factory=resource_factory) \
        .add_view(image)

    config.add_route(
        'feature_attachment.item', itmurl,
        factory=resource_factory) \
        .add_view(iget, request_method='GET') \
        .add_view(iput, request_method='PUT') \
        .add_view(idelete, request_method='DELETE')

    config.add_route(
        'feature_attachment.collection', colurl,
        factory=resource_factory) \
        .add_view(cget, request_method='GET') \
        .add_view(cpost, request_method='POST')