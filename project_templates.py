"""Worked-example project templates surfaced via the dashboard's empty-state
prompt chips. A click on a chip opens /new pre-filled with one of these,
giving a brand-new user a populated form to edit — much lower-friction
than staring at a blank one.

Numbers are illustrative, not authoritative. Every cost/benefit is a
realistic-but-invented figure intended to demonstrate the methodology
(target / strategy / alternatives, hard costs, soft costs, WTP-style
benefits) rather than to be a recommendation. The garden example is
intentionally identical to the one shown on the public landing page so
the demo feels coherent for visitors who arrive that way.

Amounts are kept as strings: the form accepts strings (parse_amount in
db.py supports "$" and "k" suffixes), and Jinja interpolates them
verbatim into the input value attributes.
"""

PROJECT_TEMPLATES = {
    'car': {
        'name': 'Should I buy a car?',
        'target': (
            'Replace public transport / occasional rideshare with a '
            'privately-owned car for the next 5 years.'
        ),
        'strategy': (
            'Buy a 2–3yo midsize sedan privately, run basic insurance and '
            'rego, sell at year 5 against expected depreciation. Avoid '
            'using it for trips a bike or PT would do equally well.'
        ),
        'alternatives': (
            'Stay car-free (current state — public transport plus rideshare '
            'for ad-hoc trips). Car-share subscription (GoGet/Carshare ~$15/hr). '
            'E-bike for ~80% of inner-city trips. Rental for the occasional '
            'weekend out of town.'
        ),
        'pros_cons': (
            'Pros: convenience, mobility, cargo capacity, weekends out of '
            'the city without rental hassle. '
            'Cons: large upfront capital, depreciation, parking, sunk '
            'maintenance, and the soft cost of induced demand — you will '
            'drive more because you can.'
        ),
        'notes': (
            'The honest read: WTP is doing most of the work. If $200/mo '
            'feels worth it just to have a car in the driveway, the math '
            'might pencil. If it does not, the rideshare/PT/bike combo '
            'wins on cost and you are rationalising a lifestyle preference.'
        ),
        'costs': [
            {'description': 'Used midsize sedan, private sale', 'amount': '25000', 'unit': 'once'},
            {'description': 'Insurance + rego', 'amount': '1800', 'unit': 'py'},
            {'description': 'Fuel + maintenance', 'amount': '200', 'unit': 'pcm'},
            {'description': 'Parking', 'amount': '50', 'unit': 'pcm'},
        ],
        'benefits': [
            {'description': 'WTP for convenience and on-demand mobility', 'amount': '200', 'unit': 'pcm'},
            {'description': 'Avoided rideshare / PT cost', 'amount': '120', 'unit': 'pcm'},
        ],
    },

    'hobby': {
        'name': 'Should I take up a new hobby?',
        'target': (
            'Try bouldering for 6 months — 1–2 sessions per week — then '
            'reassess in October.'
        ),
        'strategy': (
            'Buy basic gear (shoes, chalk), sign up to the closest gym '
            'on a 6-month membership, do an intro class to learn knots '
            'and basic technique, then go regularly. If I am not making '
            'it 4+ times a month by month 3, drop it.'
        ),
        'alternatives': (
            'Stay with current routine (running + weekly tennis). Try '
            'yoga instead — lower upfront, easier scheduling, less '
            'social. Pick up an instrument again — very different time '
            'profile, almost zero physical benefit.'
        ),
        'pros_cons': (
            'Pros: fitness, novel problem-solving, gyms have a real '
            'community, indoor option for bad weather. '
            'Cons: time competes with existing exercise, real injury '
            'risk for fingers/shoulders, gear is sunk if I do not stick '
            'with it.'
        ),
        'notes': (
            'For a hobby the math is mostly WTP. The question is "is the '
            'enjoyment + fitness genuinely worth $80/mo to me?" — not "does '
            'it pay back". The 6-month checkpoint is the important bit.'
        ),
        'costs': [
            {'description': 'Climbing shoes, chalk bag, brush', 'amount': '250', 'unit': 'once'},
            {'description': 'Gym membership', 'amount': '50', 'unit': 'pcm'},
            {'description': 'Time at gym (incl. travel)', 'amount': '4', 'unit': 'hours_pcm'},
        ],
        'benefits': [
            {'description': 'WTP for the activity itself (fitness + fun + social)', 'amount': '80', 'unit': 'pcm'},
            {'description': 'Replaces existing gym membership', 'amount': '40', 'unit': 'pcm'},
        ],
    },

    'job': {
        'name': 'Should I quit my job?',
        'target': (
            'Leave current role for a 6-month break to recover from '
            'low-grade burnout and seriously test a side-project idea.'
        ),
        'strategy': (
            'Build to 9 months of cash runway before the last day. '
            'Spend the first 4 weeks not working at all. Then put 20 hrs/wk '
            'into the side project for 4 months and 4 weeks job-searching. '
            'If the side project has not shown clear pull by month 5, '
            'return to employment.'
        ),
        'alternatives': (
            'Stay and renegotiate scope or hours. Stay and take long '
            'service / extended leave instead of resigning. Stay and run '
            'the side project on weekends. Move to a different employer '
            'in the same field for a step-up rather than a break.'
        ),
        'pros_cons': (
            'Pros: rest before burnout becomes structural, dedicated time '
            'to test the side project, mental space for long-term '
            'thinking I never get during the work week. '
            'Cons: 6 months of forgone after-tax income is a large '
            'number, harder to re-enter at the same level, lose company '
            'benefits and superannuation contributions, opportunity cost '
            'if the side project fails.'
        ),
        'notes': (
            'Most people overestimate "side project" upside; weight it '
            'honestly. Useful inversion: if I knew the side project would '
            'definitely fail, would I still want this break? If yes, the '
            'math is just on the burnout-avoidance and rest WTP. If no, '
            'I am betting on the project — be honest about the odds.'
        ),
        'costs': [
            {'description': 'Forgone after-tax income (6 months)', 'amount': '8000', 'unit': 'pcm'},
            {'description': 'Health insurance + lost benefits', 'amount': '200', 'unit': 'pcm'},
            {'description': 'Side-project setup (tools, hosting, services)', 'amount': '500', 'unit': 'once'},
        ],
        'benefits': [
            {'description': 'WTP for 6 months of freedom and mental reset', 'amount': '3000', 'unit': 'pcm'},
            {'description': 'Side-project upside (probability-weighted)', 'amount': '1000', 'unit': 'pcm'},
            {'description': 'Avoided burnout cost (medical leave next year, P=0.3)', 'amount': '500', 'unit': 'pcm'},
        ],
    },

    'garden': {
        'name': 'Should I start a vegetable garden?',
        'target': (
            'A backyard plot productive enough to cover most of our '
            'greens, year-round.'
        ),
        'strategy': (
            'Raised beds along the back fence, drip irrigation on a '
            'timer, compost from kitchen waste. Spring weekends for '
            'planting; maintenance-only after that.'
        ),
        'alternatives': (
            'CSA box ($60/wk) — gives the food without the time, but '
            'loses the WTP-of-having-a-garden bit entirely. Nothing — '
            'keep buying veggies at the supermarket. Smaller herb-only '
            'planters as a low-commitment trial.'
        ),
        'pros_cons': (
            'Pros: nicer-quality veg, garden as object of pride, time '
            'outdoors, easy to involve kids. '
            'Cons: time-intensive, very slow to break even, vulnerable '
            'to peak-summer holidays without a watering plan, weather '
            'risk, the slugs.'
        ),
        'notes': (
            'Auto-calc says ~47 month payback — marginal as a pure '
            'financial decision. Worth doing for the WTP side, not the '
            'maths. Putting numbers on the WTP makes that explicit.'
        ),
        'costs': [
            {'description': 'Raised beds, soil, drip irrigation', 'amount': '1200', 'unit': 'once'},
            {'description': 'Seeds, compost, replacements', 'amount': '25', 'unit': 'pcm'},
            {'description': 'Initial setup time', 'amount': '50', 'unit': 'hours'},
            {'description': 'Ongoing time (planting + maintenance)', 'amount': '4', 'unit': 'hours_pcm'},
        ],
        'benefits': [
            {'description': 'Replaces grocery vegetables', 'amount': '60', 'unit': 'pcm'},
            {'description': 'WTP for having a really nice garden', 'amount': '500', 'unit': 'py'},
        ],
    },
}
