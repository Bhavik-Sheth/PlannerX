# Planner package
import warnings

# Suppress LangChain Nvidia warning about unknown model types (e.g. minimax-m3)
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    module="langchain_nvidia_ai_endpoints.*"
)
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=".*minimax-m3.*"
)

