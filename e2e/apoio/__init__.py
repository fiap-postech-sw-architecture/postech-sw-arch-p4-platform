"""Codigo auxiliar do E2E: esperas, mascara de segredos, dados, parsers e kubectl.

Tudo o que nao precisa de cluster para ser testado fica aqui, com testes em
``tests/test_e2e_apoio.py``. O que fala com o cluster (``conftest.py``,
``servicos.py`` e os steps) usa estes modulos.
"""
