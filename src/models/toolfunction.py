from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ParamProperties(BaseModel):
    # define properties for individual parameters within a tool's function
    type: Literal["string", "integer", "number", "boolean", "array", "object"]
    description: Optional[str] = None


class ToolParams(BaseModel):
    # define overall schema for all params tool function accepts
    type: Literal["object"] = "object"
    properties: Dict[str, ParamProperties] = Field(
        ..., description="Properties for the tool's parameters."
    )
    required: Optional[List[str]] = Field(
        None, description="List of required parameter names."
    )


class ToolFunction(BaseModel):
    # define the details of a specific function to be called by llm
    name: str = Field(..., description="The name of the function to call.")
    description: Optional[str] = Field(
        None, description="A description of what the function does."
    )
    parameters: ToolParams = Field(
        ...,
        description="The parameters the function accepts, described as a JSON Schema object.",
    )


class LLMToolSchema(BaseModel):
    # complete schema for tool in format expected by llm
    type: Literal["function"] = (
        "function"  # For OpenRouter's current tool calling, this is "function"
    )
    function: ToolFunction = Field(
        ..., description="The definition of the function tool."
    )


# Ensure recursive models are updated
ParamProperties.model_rebuild()
