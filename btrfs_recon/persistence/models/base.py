from __future__ import annotations

from datetime import datetime
from typing import Type, TYPE_CHECKING

import inflection
import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy.orm import declarative_base, declared_attr
from sqlalchemy_repr import RepresentableBase

from btrfs_recon import structure

if TYPE_CHECKING:
    from btrfs_recon.persistence.serializers import StructSchema, registry
    from .address import Address
    from .tree_node import LeafItem

__all__ = [
    'Base',
    'BaseModel',
    'BaseStruct',
    'BaseLeafItemData',
]

Base = declarative_base(cls=RepresentableBase)


class BaseModel(Base):
    __abstract__ = True
    __table__: sa.Table

    @declared_attr
    def __tablename__(cls) -> str:
        return inflection.underscore(cls.__name__)

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)

    created_at = sa.Column(sa.DateTime, server_default=sa.func.now(), nullable=False)
    updated_at = sa.Column(sa.DateTime, server_default=sa.func.now(), onupdate=datetime.utcnow(), nullable=False)


class BaseStruct(BaseModel):
    """Base model for all addressable structures"""
    __abstract__ = True

    _version = sa.Column(sa.Integer, server_default='0', doc="Version number of this model's serializer at time of parsing")

    address_id: declared_attr[int] = declared_attr(lambda cls: sa.Column(sa.ForeignKey('address.id'), nullable=False))
    address: declared_attr[Address] = declared_attr(lambda cls: orm.relationship('Address', lazy='joined'))

    @classmethod
    def get_registry_entry(cls) -> registry.RegistryEntry:
        from btrfs_recon.persistence.serializers import registry
        if entry := registry.find_by_model(cls):
            return entry
        else:
            raise KeyError(f'Model {cls.__name__} was not found in registry')

    @classmethod
    def get_schema_class(cls) -> Type[StructSchema]:
        entry = cls.get_registry_entry()
        return entry.schema

    @classmethod
    def get_struct_class(cls) -> Type[structure.Struct]:
        entry = cls.get_registry_entry()
        return entry.struct


class BaseLeafItemData(BaseStruct):
    """Base model for all items specified in leaf nodes"""
    __abstract__ = True

    leaf_item_id: declared_attr[int] = declared_attr(lambda cls: sa.Column(sa.ForeignKey('leaf_item.id'), nullable=False))
    leaf_item: declared_attr[LeafItem] = declared_attr(lambda cls: orm.relationship('LeafItem'))
