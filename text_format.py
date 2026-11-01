"""Piccole correzioni di presentazione; nessuna ricostruzione di formule corrotte."""

import re

FORMATTING_INSTRUCTIONS = """
Usa Markdown semplice per titoli, elenchi e grassetto, senza racchiudere tutta la
risposta in un blocco di codice. Scrivi le formule in notazione testuale leggibile:
per esempio H(m1) = H(m2), 2^(N/2), c = p^E mod N, A -> B, beta * IB.
Non usare delimitatori LaTeX, dollari o comandi con backslash nelle formule.
Non cambiare il significato matematico; se la fonte e' illeggibile, dichiaralo.
"""


def readable_text(text):
    # Rimuovi solo un involucro Markdown esplicito, non i blocchi di codice interni.
    wrapped = re.fullmatch(r'\s*```(?:markdown|md|text|plaintext)\s*\n(.*?)\n```\s*', text, re.DOTALL)
    if wrapped:
        text = wrapped.group(1)

    def formula(match):
        value = next(group for group in match.groups() if group is not None)
        commands = {'rightarrow': '->', 'leftarrow': '<-', 'Rightarrow': '=>',
                    'leftrightarrow': '<->', 'neq': '!=', 'ne': '!=', 'leq': '<=',
                    'geq': '>=', 'times': '*', 'cdot': '*', 'bmod': 'mod', 'mod': 'mod',
                    'alpha': 'alpha', 'beta': 'beta', 'gamma': 'gamma', 'theta': 'theta',
                    'lambda': 'lambda', 'pi': 'pi', 'sigma': 'sigma', 'Delta': 'Delta',
                    'approx': '~', 'infty': 'infinito'}
        value = re.sub(r'\\([A-Za-z]+)', lambda item: commands.get(item[1], item[0]), value)
        # Converte solo costrutti semplici e completi; quelli sconosciuti restano visibili.
        value = re.sub(r'\\frac\{([^{}]+)\}\{([^{}]+)\}', r'(\1)/(\2)', value)
        value = re.sub(r'\\(?:text|mathrm|mathbf)\{([^{}]+)\}', r'\1', value)
        value = re.sub(r'([_^])\{([^{}]+)\}', r'\1(\2)', value)
        return value.strip()

    return re.sub(r'\$\$(.*?)\$\$|\$([^\n$]+)\$|\\\((.*?)\\\)|\\\[(.*?)\\\]',
                  formula, text, flags=re.DOTALL)
