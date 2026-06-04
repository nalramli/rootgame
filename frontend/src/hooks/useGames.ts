import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

const djangoUrl = import.meta.env.VITE_DJANGO_URL || "";

import type { components } from "../api/types";
import { gameKeys } from "../api/queryKeys";

export type FactionChoice = components["schemas"]["FactionChoiceEntry"];
export type PlayerInfo = components["schemas"]["PlayerPublic"];
export type GameListItem = components["schemas"]["GameSession"];

const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
  const token = localStorage.getItem("accessToken");
  const headers = {
    ...options.headers,
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) {
    if (response.status === 401) {
      // Handle unauthorized (optional: refresh token or redirect)
    }
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response;
};

export const useActiveGames = () => {
  return useQuery<GameListItem[]>({
    queryKey: gameKeys.gameList("active"),
    queryFn: async () => {
      const resp = await fetchWithAuth(`${djangoUrl}/api/games/active/`);
      return resp.json();
    },
  });
};

export const useJoinableGames = () => {
  return useQuery<GameListItem[]>({
    queryKey: gameKeys.gameList("joinable"),
    queryFn: async () => {
      const resp = await fetchWithAuth(`${djangoUrl}/api/games/joinable/`);
      return resp.json();
    },
  });
};

export const useCreateGame = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: {
      map_label?: string;
      faction_options?: { faction: string }[];
    }) => {
      const resp = await fetchWithAuth(`${djangoUrl}/api/game/create/`, {
        method: "POST",
        body: JSON.stringify(data),
      });
      return resp.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: gameKeys.gameLists() });
    },
  });
};

export const useJoinGame = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (gameId: number) => {
      const resp = await fetchWithAuth(
        `${djangoUrl}/api/game/join/${gameId}/`,
        {
          method: "PATCH",
        },
      );
      if (resp.status === 204) return null;
      return resp.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: gameKeys.gameLists() });
    },
  });
};

export const useGameSession = (gameId: number | null) => {
  return useQuery<GameListItem>({
    queryKey: gameKeys.session(gameId as number),
    queryFn: async () => {
      const resp = await fetchWithAuth(
        `${djangoUrl}/api/game/${gameId}/session/`,
      );
      return resp.json();
    },
    enabled: !!gameId,
  });
};

export const useStartGame = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (gameId: number) => {
      const resp = await fetchWithAuth(
        `${djangoUrl}/api/game/start/${gameId}/`,
        {
          method: "PATCH",
        },
      );
      if (resp.status === 204) return null;
      return resp.json();
    },
    onSuccess: (_, gameId) => {
      queryClient.invalidateQueries({ queryKey: gameKeys.session(gameId) });
    },
  });
};
export const useDeleteGame = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (gameId: number) => {
      const resp = await fetchWithAuth(
        `${djangoUrl}/api/game/delete/${gameId}/`,
        { method: "DELETE" },
      );
      if (resp.status === 204) return null;
      return resp.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: gameKeys.gameLists() });
    },
  });
};

export const usePickFaction = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (data: { gameId: number; faction: string }) => {
      const resp = await fetchWithAuth(
        `${djangoUrl}/api/game/pick-faction/${data.gameId}/`,
        {
          method: "PATCH",
          body: JSON.stringify({ faction: data.faction }),
        },
      );
      if (resp.status === 204) return null;
      return resp.json();
    },
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: gameKeys.session(variables.gameId),
      });
    },
  });
};
