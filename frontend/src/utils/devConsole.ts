import { QueryClient } from "@tanstack/react-query";
import { gameKeys } from "../api/queryKeys";

// Expose to window for console access
declare global {
  interface Window {
    mockCraftedItems: {
      inject: (faction: string, items: any[]) => void;
      catsWithBootsAndCoin: () => void;
      birdsWithMultiple: () => void;
      clear: (faction: string) => void;
    };
    mockRats: {
      setHoard: (commandItems: any[], prowessItems: any[]) => void;
      setMood: (mood: string) => void;
      fullHoard: () => void;
      partialHoard: () => void;
    };
  }
}

let queryClientInstance: QueryClient | null = null;
let gameIdInstance: number | null = null;

export function initDevConsole(queryClient: QueryClient, gameId: number) {
  queryClientInstance = queryClient;
  gameIdInstance = gameId;

  window.mockCraftedItems = {
    inject: (faction: string, items: any[]) => {
      if (!queryClientInstance || !gameIdInstance) {
        console.error("Dev console not initialized. Open a player board first.");
        return;
      }

      const factionMap: Record<string, "cats" | "birds" | "crows" | "woodland-alliance" | "rats"> = {
        cats: "cats",
        ca: "cats",
        birds: "birds",
        bi: "birds",
        crows: "crows",
        cr: "crows",
        wa: "woodland-alliance",
        "woodland-alliance": "woodland-alliance",
        rats: "rats",
        ra: "rats",
      };

      const mappedFaction = factionMap[faction.toLowerCase()];
      if (!mappedFaction) {
        console.error(
          `Unknown faction: ${faction}. Use: cats, birds, crows, or wa`
        );
        return;
      }

      const currentData = queryClientInstance!.getQueryData(
        gameKeys.faction(gameIdInstance!, mappedFaction)
      );

      if (currentData) {
        queryClientInstance!.setQueryData(
          gameKeys.faction(gameIdInstance!, mappedFaction),
          {
            ...currentData,
            crafted_items: items,
          }
        );
        console.log(
          `✓ Injected ${items.length} crafted items for ${mappedFaction}`
        );
      } else {
        console.error(
          `No query data found for ${mappedFaction}. Make sure the player board is open.`
        );
      }
    },

    catsWithBootsAndCoin: () => {
      window.mockCraftedItems.inject("cats", [
        {
          id: 1,
          item: { value: "1", label: "Boots" },
          exhausted: true,
        },
        {
          id: 2,
          item: { value: "3", label: "Coin" },
          exhausted: false,
        },
      ]);
    },

    birdsWithMultiple: () => {
      window.mockCraftedItems.inject("birds", [
        {
          id: 1,
          item: { value: "4", label: "Crossbow" },
          exhausted: false,
        },
        {
          id: 2,
          item: { value: "6", label: "Sword" },
          exhausted: false,
        },
        {
          id: 3,
          item: { value: "0", label: "Bag" },
          exhausted: true,
        },
        {
          id: 4,
          item: { value: "2", label: "Coin" },
          exhausted: false,
        },
        {
          id: 5,
          item: { value: "5", label: "Hammer" },
          exhausted: true,
        },
        {
          id: 6,
          item: { value: "1", label: "Boots" },
          exhausted: false,
        },
        {
          id: 7,
          item: { value: "3", label: "Tea" },
          exhausted: true,
        },
      ]);
    },

    clear: (faction: string) => {
      window.mockCraftedItems.inject(faction, []);
    },
  };

  // --- Rats mock helpers ---
  window.mockRats = {
    setHoard: (commandItems: any[], prowessItems: any[]) => {
      if (!queryClientInstance || !gameIdInstance) {
        console.error("Dev console not initialized. Open a player board first.");
        return;
      }
      const current = queryClientInstance.getQueryData(
        gameKeys.faction(gameIdInstance, "rats")
      );
      if (!current) {
        console.error("No Rats query data found. Open the Rats player board first.");
        return;
      }
      queryClientInstance.setQueryData(gameKeys.faction(gameIdInstance, "rats"), {
        ...current,
        command_items: commandItems,
        prowess_items: prowessItems,
      });
      console.log(`✓ Rats hoard set — Command: ${commandItems.length} items, Prowess: ${prowessItems.length} items`);
    },

    setMood: (mood: string) => {
      if (!queryClientInstance || !gameIdInstance) {
        console.error("Dev console not initialized. Open a player board first.");
        return;
      }
      const current = queryClientInstance.getQueryData(
        gameKeys.faction(gameIdInstance, "rats")
      );
      if (!current) {
        console.error("No Rats query data found. Open the Rats player board first.");
        return;
      }
      const validMoods = ["bitter", "grandiose", "jubilant", "lavish", "relentless", "rowdy", "stubborn", "wrathful"];
      if (!validMoods.includes(mood)) {
        console.error(`Unknown mood: "${mood}". Valid moods: ${validMoods.join(", ")}`);
        return;
      }
      queryClientInstance.setQueryData(gameKeys.faction(gameIdInstance, "rats"), {
        ...current,
        mood: { mood_type: mood },
      });
      console.log(`✓ Rats mood set to: ${mood}`);
    },

    fullHoard: () => {
      window.mockRats.setHoard(
        [
          { item: { value: "3", label: "Tea" } },
          { item: { value: "5", label: "Hammer" } },
          { item: { value: "1", label: "Boots" } },
          { item: { value: "2", label: "Coin" } },
        ],
        [
          { item: { value: "4", label: "Crossbow" } },
          { item: { value: "0", label: "Bag" } },
        ]
      );
    },

    partialHoard: () => {
      window.mockRats.setHoard(
        [
          { item: { value: "1", label: "Boots" } },
        ],
        []
      );
    },
  };

  console.log(
    "✓ Dev console ready! Use window.mockCraftedItems and window.mockRats in the console.\n" +
      "mockCraftedItems:\n" +
      "  mockCraftedItems.catsWithBootsAndCoin()\n" +
      "  mockCraftedItems.birdsWithMultiple()\n" +
      "  mockCraftedItems.inject('faction', items)\n" +
      "  mockCraftedItems.clear('faction')\n" +
      "mockRats:\n" +
      "  mockRats.fullHoard()           — 4 command + 2 prowess items\n" +
      "  mockRats.partialHoard()        — 1 command item\n" +
      "  mockRats.setHoard(cmd, prw)    — inject arbitrary arrays\n" +
      "  mockRats.setMood('wrathful')   — any of: bitter, grandiose, jubilant, lavish, relentless, rowdy, stubborn, wrathful"
  );
}
