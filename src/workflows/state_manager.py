import pickle
from datetime import datetime
from typing import Dict, Optional

from src.models.agent_schemas import GmailAgentState


class StateManager:
    """
    Custom state manager for LangGraph workflow state serialization. Presently only supports memeory and file backend storage.

    Args:
        storage_backend: The storage backend to use ["memory", "file"]

    Example:
        state_manager = StateManager(storage_backend="memory")
        state_manager.save_state(state)
        state_manager.load_state(user_id)
    """

    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._memory_store: Dict[str, bytes] = {}

    def save_state(self, state: GmailAgentState) -> None:
        """
        Save state with proper serialization

        Args:
            state: GmailAgentState object to save

        Raises:
            ValueError: If the state is not a GmailAgentState object
        """
        if not isinstance(state, GmailAgentState):
            raise ValueError(f"Expected GmailAgentState, got {type(state)}")

        serialized_data = {
            "type": "GmailAgentState",
            "version": "1.0",
            "timestamp": datetime.now().isoformat(),
            "data": state.model_dump(),
        }

        serialized_bytes = pickle.dumps(serialized_data)

        if self.storage_backend == "memory":
            self._memory_store[state.user_id] = serialized_bytes
        elif self.storage_backend == "file":
            self._save_to_file(state.user_id, serialized_bytes)

    def load_state(self, user_id: str) -> Optional[GmailAgentState]:
        """
        Load state with proper deserialization

        Args:
            user_id: User ID to load state for

        Returns:
            GmailAgentState object or None if not found

        Raises:
            ValueError: If the serialized data is not a dictionary
            ValueError: If the serialized data is not a GmailAgentState object
        """
        try:
            if self.storage_backend == "memory":
                serialized_bytes = self._memory_store.get(user_id)
            elif self.storage_backend == "file":
                serialized_bytes = self._load_from_file(user_id)
            else:
                serialized_bytes = None

            if not serialized_bytes:
                return None

            # deserialize with type checking and validate
            serialized_data = pickle.loads(serialized_bytes)

            if not isinstance(serialized_data, dict):
                raise ValueError("Invalid serialized state format")

            if serialized_data.get("type") != "GmailAgentState":
                raise ValueError(
                    f"Expected GmailAgentState, got {serialized_data.get('type')}"
                )

            # reconstruct the state object
            state_data = serialized_data["data"]

            actual_state = extract_langgraph_state(state_data)
            return GmailAgentState(**actual_state)

        except Exception as e:
            print(f"Error loading state for user {user_id}: {e}")
            return None


def extract_langgraph_state(state_dict: dict) -> dict:
    """
    Extract the current state from LangGraph's nested dictionary structure

    Args:
        state_dict: Dictionary that might be nested from LangGraph

    Returns:
        Flat dictionary with the current state data
    """
    if (
        isinstance(state_dict, dict)
        and len(state_dict) == 1
        and isinstance(next(iter(state_dict.values())), dict)
    ):
        # LangGraph nested structure: {'node_name': {'current_state': 'data'}}
        return next(iter(state_dict.values()))
    else:
        # Direct state structure
        return state_dict


# global state manager instance used for saving and loading state
state_manager = StateManager()


# helper functions for backward compatibility
def save_state_to_store(state: GmailAgentState) -> None:
    """Save state using the state manager"""
    state_manager.save_state(state)


def load_state_from_store(user_id: str) -> Optional[GmailAgentState]:
    """Load state using the state manager"""
    return state_manager.load_state(user_id)
