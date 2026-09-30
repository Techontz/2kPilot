from __future__ import annotations

from pydantic import BaseModel

from fxrobot.broker_engine.registry import ConnectorDescriptor, ConnectorStatus


class ConnectorFieldOut(BaseModel):
    name: str
    label: str
    secret: bool
    help: str


class ConnectorOut(BaseModel):
    id: str
    name: str
    status: ConnectorStatus
    status_detail: str
    fields: list[ConnectorFieldOut]

    @classmethod
    def from_descriptor(cls, d: ConnectorDescriptor) -> ConnectorOut:
        return cls(
            id=d.id,
            name=d.name,
            status=d.status,
            status_detail=d.status_detail,
            fields=[
                ConnectorFieldOut(name=f.name, label=f.label, secret=f.secret, help=f.help)
                for f in d.fields
            ],
        )
