"""The translation gateway's routing core.

One endpoint fronts several engines. Which one answers is decided the way
svc-ai-litellm decides between models, through the package svc-ai-s1 owns and
stages here, so the sampling rule, the learning log and the blind verdict
exist once for both.
"""

from .engines import ChatModelEngine as ChatModelEngine
from .engines import LibreTranslateEngine as LibreTranslateEngine
from .errors import EngineRefusedError as EngineRefusedError
from .errors import GatewayError as GatewayError
from .errors import MangledTermError as MangledTermError
from .errors import NoBackendError as NoBackendError
from .failures import FailureLog as FailureLog
from .gateway import Gateway as Gateway
from .memory import WeblateClient as WeblateClient
from .memory import WeblateGlossary as WeblateGlossary
from .memory import WeblateMemory as WeblateMemory
from .router import Router as Router
from .router import saturated as saturated
from .signature import cache_key as cache_key
from .signature import signature as signature
