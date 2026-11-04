"""The decider mechanism svc-ai-s1 owns and its consumers stage.

svc-ai-litellm routes a chat request between models and web-svc-translate
routes a translation between engines; both take the same decision, so the
sampling rule, the learning log and the blind verdict live here once. Each
consumer stages this package into its own build context the way the MCP
adapter's is staged per instance.
"""

from .history import History as History
from .history import record_of as record_of
from .judge import Decider as Decider
from .sampling import Sampler as Sampler
