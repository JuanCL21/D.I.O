import sys
import dio.core.config as _core_config

# Hacer que 'config' y 'dio.core.config' apunten a la misma instancia de módulo
# para que unittest.mock.patch.object(config, ...) patchee de forma unificada.
sys.modules[__name__] = _core_config
