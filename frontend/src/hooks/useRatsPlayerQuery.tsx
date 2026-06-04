import { useQuery } from "@tanstack/react-query";
import { getFactionPlayerInfoQueryOptions } from "./useFactionPlayerInfoQuery";
import type { components } from "../api/types";

export const useRatsPlayerQuery = (
  gameId: number,
  enabled: boolean = true,
): {
  publicInfo: components["schemas"]["Rats"] | undefined;
  isLoading: boolean;
  isError: boolean;
  isSuccess: boolean;
} => {
  const {
    data: publicInfo,
    isError,
    isLoading,
    isSuccess,
  } = useQuery<components["schemas"]["Rats"]>(
    getFactionPlayerInfoQueryOptions<components["schemas"]["Rats"]>(
      gameId,
      "rats",
      enabled,
    ),
  );

  return { publicInfo, isLoading, isError, isSuccess };
};

export default useRatsPlayerQuery;
