import type { components } from "../api/types";

type MoodType = components["schemas"]["ValidMoodsEnum"];

interface MoodInfo {
  label: string;
  item: string | null;
  description: string;
}

export const MOOD_DATA: Record<MoodType, MoodInfo> = {
  bitter: {
    label: "Bitter",
    item: "Hammer",
    description:
      "In battle in your warlord's clearing, before the roll you may remove any number of mob tokens from your warlord's clearing and any clearings adjacent to it. Place warriors in your warlord's clearing equal to the number of mob tokens you removed.",
  },
  grandiose: {
    label: "Grandiose",
    item: "Tea",
    description:
      "This turn, perform your Advance the Warlord step and your Command the Hundreds step in reverse order: Advance the Warlord first, then Command the Hundreds.",
  },
  jubilant: {
    label: "Jubilant",
    item: "Boot",
    description:
      "Whenever you take the Incite action in your warlord's clearing, after placing the mob token you may—up to four times—roll the mob die and place a mob token in a matching clearing that has no mob token but is adjacent to any clearing with a mob token.",
  },
  lavish: {
    label: "Lavish",
    item: null,
    description:
      "At the end of your Birdsong, you may remove any number of items from your Hoard permanently. For each item you remove, place two warriors into your warlord's clearing. When done, shift items in your Hoard to fill its tracks from left to right.",
  },
  relentless: {
    label: "Relentless",
    item: "Sack",
    description:
      "Whenever you take the Advance the Warlord action and both move and battle, you may then either move your warlord with any Hundreds warriors or battle in your warlord's clearing.",
  },
  rowdy: {
    label: "Rowdy",
    item: "Coin",
    description:
      "In Evening, draw one more card. If your warlord's clearing has three or more enemy pieces (even from different enemies), draw two more cards instead.",
  },
  stubborn: {
    label: "Stubborn",
    item: "Crossbow",
    description:
      "In battle in your warlord's clearing, you ignore the first hit you take. (Does not combine with other abilities that let you ignore the first hit.)",
  },
  wrathful: {
    label: "Wrathful",
    item: "Sword",
    description:
      "As attacker in battle in your warlord's clearing, you deal an extra hit.",
  },
};
