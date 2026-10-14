"""Dados unicos de cada execucao e cenario: CPF, placa, codigos de preco e e-mails.

O cluster nao e limpo entre execucoes, entao nada e fixo: o CPF e a placa saem
de sorteio, e os codigos de servico e peca levam o identificador da execucao e
o numero do cenario (``SRV-E2E-<execucao>-<n>``, ``PEC-E2E-<execucao>-<n>``).
"""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    import random
    from collections.abc import Sequence

# SystemRandom e um random.Random: os testes passam uma semente fixa no lugar.
_ALEATORIO: Final = secrets.SystemRandom()
_LETRAS: Final = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
# A placa que o erasure LGPD grava no lugar da real: nunca a de um cliente.
_PLACA_SENTINELA: Final = "AAA0A00"


def _digito_verificador(digitos: Sequence[int]) -> int:
    """Digito do CPF (modulo 11) sobre os 9 ou 10 primeiros digitos."""
    peso = len(digitos) + 1
    soma = sum(digito * (peso - posicao) for posicao, digito in enumerate(digitos))
    return (soma * 10 % 11) % 10


def cpf_valido(rng: random.Random = _ALEATORIO) -> str:
    """CPF de 11 digitos com os dois verificadores certos, nunca de digitos iguais."""
    while True:
        base = [rng.randrange(10) for _ in range(9)]
        if len(set(base)) > 1:
            break
    primeiro = _digito_verificador(base)
    segundo = _digito_verificador([*base, primeiro])
    return "".join(str(digito) for digito in (*base, primeiro, segundo))


def cpf_invalido(rng: random.Random = _ALEATORIO) -> str:
    """CPF com o ultimo digito verificador trocado: so o modulo 11 o recusa."""
    cpf = cpf_valido(rng)
    return cpf[:-1] + str((int(cpf[-1]) + 1) % 10)


def placa_mercosul(rng: random.Random = _ALEATORIO) -> str:
    """Placa do padrao Mercosul (``ABC1D23``), diferente da sentinela do erasure."""
    while True:
        placa = (
            "".join(rng.choice(_LETRAS) for _ in range(3))
            + str(rng.randrange(10))
            + rng.choice(_LETRAS)
            + f"{rng.randrange(100):02d}"
        )
        if placa != _PLACA_SENTINELA:
            return placa


def id_da_execucao(rng: random.Random = _ALEATORIO) -> str:
    """Seis hexadecimais maiusculos que separam esta execucao das anteriores."""
    return "".join(rng.choice("0123456789ABCDEF") for _ in range(6))


def codigo(prefixo: str, execucao: str, numero: int) -> str:
    """``SRV-E2E-3FA9C1-4``: formato aceito pelo Billing e pelo estoque."""
    return f"{prefixo}-E2E-{execucao}-{numero}"


def email_de_usuario(execucao: str, papel: str) -> str:
    return f"e2e-{execucao.lower()}-{papel}@e2e.pytstop.dev"


def email_de_cliente(execucao: str, numero: int) -> str:
    return f"cliente-{execucao.lower()}-{numero}@clientes.pytstop.dev"


def senha_aleatoria() -> str:
    """32 hexadecimais: passa a regra de 12 caracteres e nao esta em lista de senhas."""
    return secrets.token_hex(16)
