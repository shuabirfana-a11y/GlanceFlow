from pydantic import BaseModel, ConfigDict


class RokidAdapterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sdk_artifact: str | None = None
    application_id: str | None = None
    device_name: str = "rokid-unconfigured"
