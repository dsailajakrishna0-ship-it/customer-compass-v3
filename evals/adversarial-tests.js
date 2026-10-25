// Stage 8.a: turns evals/adversarial-prompts.json into promptfoo test cases.
// Each attack must come back guardrail.flagged=true, each benign prompt false.
const cases = require('./adversarial-prompts.json');

module.exports = () =>
  cases.map((c) => ({
    description: `${c.id} (${c.category})`,
    vars: { prompt: c.prompt },
    assert: [
      {
        type: 'javascript',
        value: `JSON.parse(output).flagged === ${c.is_attack}`,
      },
    ],
  }));
