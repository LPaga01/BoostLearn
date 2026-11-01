import unittest
from text_format import readable_text


class TextFormatTests(unittest.TestCase):
    def test_common_formulas_keep_their_meaning(self):
        text = r'$m_1 \neq m_2$ e $H(m_1) = H(m_2)$; $2^{N/2}$; $A \rightarrow B$; $c = p^E \bmod N$'
        self.assertEqual(readable_text(text), 'm_1 != m_2 e H(m_1) = H(m_2); 2^(N/2); A -> B; c = p^E mod N')

    def test_fractions_and_text_commands(self):
        self.assertEqual(readable_text(r'\(\frac{a+b}{c}\) e $\text{RSA}$'), '(a+b)/(c) e RSA')

    def test_normal_text_and_prices_are_unchanged(self):
        text = '## Titolo\n**Concetto** e 2 * 3 * 4; prezzo $5.\nFormula già leggibile: beta * IB.'
        self.assertEqual(readable_text(text), text)

    def test_markdown_wrapper_removed_but_code_blocks_preserved(self):
        self.assertEqual(readable_text('```markdown\n## Titolo\nTesto\n```'), '## Titolo\nTesto')
        code = 'Esempio:\n```python\nx = 1\n```'
        self.assertEqual(readable_text(code), code)

    def test_unknown_commands_are_not_guessed(self):
        self.assertEqual(readable_text(r'$\unknown{x}$'), r'\unknown{x}')
