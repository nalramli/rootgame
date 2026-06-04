import { useQueries } from "@tanstack/react-query";
import { type FactionLabel, labelToRoute } from "../utils/factionUtils";
import { getFactionPlayerInfoQueryOptions } from "./useFactionPlayerInfoQuery";
import { type FactionValue } from "../utils/factionUtils";

export type TokenTableType = {
  faction: FactionLabel;
  tokenType: string;
  clearing_number: number | null;
};

const tabulateTokens = (faction: FactionLabel, data: any) => {
  const tokenTable: TokenTableType[] = [];
  type TokenItem = {
    player_name: string;
    clearing_number: number;
  };
  type TokenWrapper = {
    token: TokenItem;
  };

  // Generic tokens object: { tokenType: TokenWrapper[] }
  const tokens: Record<string, TokenWrapper[]> = data?.tokens ?? {};
  for (const tokenType of Object.keys(tokens)) {
    const tokensOfType = tokens[tokenType] ?? [];
    for (const token of tokensOfType) {
      tokenTable.push({
        faction,
        tokenType,
        clearing_number: token.token.clearing_number ?? null,
      });
    }
  }

  return tokenTable;
};

const useTokenTable = (
  gameId: number,
  factions: FactionLabel[],
  enabled: boolean = true,
) => {
  const results = useQueries({
    queries: factions.map((faction) => ({
      ...getFactionPlayerInfoQueryOptions(
        gameId,
        labelToRoute(faction) as FactionValue,
        enabled,
      ),
      select: (data: any) => tabulateTokens(faction, data),
    })),
  });

  const isLoading = results.some((r) => r.isLoading);
  const isError = results.some((r) => r.isError);
  const isSuccess = results.every((r) => r.isSuccess);

  const combinedTable = results.flatMap((r) => r.data ?? []);
  // console.log(combinedTable);

  return { tokenTable: combinedTable, isLoading, isError, isSuccess };
};

export default useTokenTable;
