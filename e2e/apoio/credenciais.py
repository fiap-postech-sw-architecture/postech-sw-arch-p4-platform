"""Usuarios do E2E: o admin do Secret e o atendente e o mecanico que ele registra."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Final, Literal

from e2e.apoio import dados
from e2e.apoio.segredos import registrar

if TYPE_CHECKING:
    from collections.abc import Callable

    from e2e.apoio.http import ClienteHttp

type Papel = Literal["admin", "atendente", "mecanico"]

AUTENTICACAO: Final = "/os/api/v1/autenticacao"
# O access token vale 15 min (JWT_EXPIRATION_MINUTES); renova antes.
VIDA_DO_TOKEN: Final = 12 * 60


class Credenciais:
    """Faz o login uma vez por sessao e renova o token pouco antes de vencer.

    O OS limita login e registro a 5 por minuto por processo, e atras do Kong todo
    cliente do kind tem o mesmo IP. Toda senha e todo token que passam por aqui
    entram na mascara de segredos antes de serem usados.
    """

    def __init__(
        self,
        http: ClienteHttp,
        *,
        admin_email: str,
        admin_senha: str,
        execucao: str,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._relogio = relogio
        self._execucao = execucao
        self._usuarios: dict[Papel, tuple[str, str]] = {
            "admin": (admin_email, admin_senha)
        }
        self._tokens: dict[Papel, tuple[str, float]] = {}
        registrar(admin_senha)

    def preparar(self) -> None:
        """Registra o atendente e o mecanico pelo admin, cada um com senha propria."""
        for papel in ("atendente", "mecanico"):
            email = dados.email_de_usuario(self._execucao, papel)
            senha = dados.senha_aleatoria()
            registrar(senha)
            self._http.pedir(
                "POST",
                f"{AUTENTICACAO}/registrar",
                token=self.token("admin"),
                json={"email": email, "senha": senha, "papel": papel},
                esperado=[201],
            )
            self._usuarios[papel] = (email, senha)

    def token(self, papel: Papel) -> str:
        """Access token do ``papel``: login na primeira vez e de novo aos 12 min."""
        emitido = self._tokens.get(papel)
        if emitido is None or self._relogio() - emitido[1] > VIDA_DO_TOKEN:
            email, senha = self._usuarios[papel]
            resposta = self._http.pedir(
                "POST",
                f"{AUTENTICACAO}/login",
                json={"email": email, "senha": senha},
                esperado=[200],
            )
            token = str(resposta.json()["access_token"])
            registrar(token)
            emitido = (token, self._relogio())
            self._tokens[papel] = emitido
        return emitido[0]
