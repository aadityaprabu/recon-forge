export const policyFields = [
  { field: 'processor_amount_tolerance_cents', group: 'amount_matching', parameter: 'absolute_tolerance_cents', patch: 'amount_tolerance_cents', label: 'Amount tolerance', unit: '¢', initial: 0 },
  { field: 'processor_settlement_window_days', group: 'settlement', parameter: 'window_business_days', patch: 'settlement_window_days', label: 'Settlement window', unit: ' days', initial: 2 },
  { field: 'processor_fixed_fee_cents', group: 'fees', parameter: 'fixed_fee_cents', patch: 'fixed_fee_cents', label: 'Fixed fee adjustment', unit: '¢', initial: 0 },
  { field: 'processor_fee_bps', group: 'fees', parameter: 'percentage_bps', patch: 'fee_bps', label: 'Percentage fee', unit: ' bps', initial: 0 },
]
export const policyProcessors = ['PROC_A', 'PROC_B', 'PROC_C', 'PROC_D']
export const policyValue = (policy, config, processor) => policy?.processor_overrides?.[processor]?.[config.group]?.[config.parameter] ?? policy?.[config.group]?.[config.parameter] ?? policy?.matching?.[config.field]?.[processor] ?? config.initial
export const patchInfo = patch => policyFields.find(config => patch?.[config.patch] != null) || policyFields[0]

export const processorNames = { PROC_A: 'Stripe', PROC_B: 'Adyen', PROC_C: 'PayPal', PROC_D: 'Square' }
export const processorLabel = (id, policy) => policy?.processor_names?.[id] || processorNames[id] || id
