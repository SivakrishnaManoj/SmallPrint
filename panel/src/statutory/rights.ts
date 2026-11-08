/**
 * UK statutory rights shown beside the cards. Fixed, general wording with a link to the
 * law itself, never derived from the page or the model, and always labelled as not legal
 * advice. Change the wording only with sign-off.
 */
export interface StatutoryRight {
  id: string;
  title: string;
  text: string;
  source: { label: string; url: string };
}

export const RIGHTS: Record<"cancel_online" | "goods" | "services", StatutoryRight> = {
  cancel_online: {
    id: "cancel_online",
    title: "14 days to change your mind",
    text:
      "When you buy online or by phone you can usually cancel within 14 days without giving a reason. " +
      "For goods the 14 days start the day after you receive them; for services, the day after you agree the contract. " +
      "Some things are excepted, such as personalised items and digital content you have started to download.",
    source: {
      label: "Consumer Contracts Regulations 2013",
      url: "https://www.legislation.gov.uk/uksi/2013/3134/contents",
    },
  },
  goods: {
    id: "goods",
    title: "Goods must be as described and work",
    text:
      "Goods must be of satisfactory quality, fit for purpose and as described. " +
      "If they are not, you can usually reject them for a full refund within 30 days.",
    source: {
      label: "Consumer Rights Act 2015, Part 1 Chapter 2",
      url: "https://www.legislation.gov.uk/ukpga/2015/15/part/1/chapter/2",
    },
  },
  services: {
    id: "services",
    title: "Services must be done with reasonable care and skill",
    text:
      "A service must be carried out with reasonable care and skill. " +
      "If it is not, you can usually ask for it to be put right or for a price reduction.",
    source: {
      label: "Consumer Rights Act 2015, Part 1 Chapter 4",
      url: "https://www.legislation.gov.uk/ukpga/2015/15/part/1/chapter/4",
    },
  },
};

/** Which rights to show for a purchase, from the extension's purchase-type signals. */
export function rightsFor(purchaseTypes: readonly string[]): StatutoryRight[] {
  const out = [RIGHTS.cancel_online];
  if (purchaseTypes.includes("product")) out.push(RIGHTS.goods);
  if (purchaseTypes.includes("subscription") || purchaseTypes.includes("contract")) out.push(RIGHTS.services);
  return out;
}
