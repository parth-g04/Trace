/**
 * TRACE Financial Formatting Helpers
 * Strict integer arithmetic and tabular unit conversion.
 */

/**
 * Formats a wei string or number into an exact ETH decimal representation.
 * Avoids precision loss by using BigInt arithmetic for minor units.
 */
export function formatWeiToEth(weiVal) {
  if (weiVal == null) return '0.00';
  try {
    const weiBig = BigInt(String(weiVal));
    const ethWhole = weiBig / 1000000000000000000n;
    const remainder = weiBig % 1000000000000000000n;
    // Format up to 4 decimal places
    const fracStr = (remainder + 1000000000000000000n).toString().slice(1, 5);
    return `${ethWhole}.${fracStr}`;
  } catch {
    return '0.00';
  }
}

/**
 * Formats integer cents into a USD dollar string ($X,XXX.XX).
 */
export function formatCentsToUsd(cents) {
  if (cents == null || isNaN(cents)) return '$0.00';
  const dollars = cents / 100;
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(dollars);
}
