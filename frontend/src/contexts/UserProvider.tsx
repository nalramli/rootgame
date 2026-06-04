import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext } from "react";
import type { UseMutationResult } from "@tanstack/react-query";

import type { components } from "../api/types";
import { gameKeys } from "../api/queryKeys";

const djangoUrl = import.meta.env.VITE_DJANGO_URL || "";

export type LoginCredentials = Omit<
  components["schemas"]["TokenObtainPair"],
  "access" | "refresh"
>;

export interface UserContextType {
  username: string | null | undefined;
  signInMutation: UseMutationResult<any, Error, LoginCredentials>;
  signOut: () => void;
  isLoading: boolean;
  isFetched: boolean;
}

const UserContext = createContext<UserContextType>({} as UserContextType);

const UserProvider = ({ children }: { children: React.ReactNode }) => {
  const queryClient = useQueryClient();
  const signIn = useMutation({
    mutationFn: async (loginData: LoginCredentials) => {
      const response = await fetch(`${djangoUrl}/api/token/`, {
        method: "POST",
        // credentials: "include",
        body: JSON.stringify({
          username: loginData.username,
          password: loginData.password,
        }),
        headers: {
          "Content-Type": "application/json",
        },
      });
      if (!response.ok) {
        throw new Error("Invalid credentials");
      }
      return response.json();
    },
    onSuccess: async (data, variables) => {
      localStorage.setItem("accessToken", data.access);
      localStorage.setItem("refreshToken", data.refresh);
      console.log("success", data);
      queryClient.setQueryData(["user"], { username: variables.username });
      queryClient.invalidateQueries({ queryKey: ["playerInfo"] });
      queryClient.invalidateQueries({ queryKey: gameKeys.gameLists() });
    },
    onError: (error) => {
      console.log("error", error);
    },
  });

  const signOut = () => {
    localStorage.removeItem("accessToken");
    localStorage.removeItem("refreshToken");
    queryClient.setQueryData(["user"], { username: null });
    queryClient.invalidateQueries();
  };

  const userInfoQuery = useQuery({
    queryKey: ["user"],
    queryFn: async (): Promise<{ username: string | null }> => {
      if (!localStorage.getItem("accessToken")) return { username: null };
      const response = await fetch(`${djangoUrl}/api/user/`, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("accessToken")}`,
          "Content-Type": "application/json",
        },
      });
      if (!response.ok) {
        localStorage.removeItem("accessToken");
        return { username: null };
      }
      return response.json();
    },
  });
  return (
    <UserContext.Provider
      value={{
        username: userInfoQuery.data?.username,
        signInMutation: signIn,
        signOut,
        isLoading: userInfoQuery.isLoading,
        isFetched: userInfoQuery.isFetched,
      }}
    >
      {children}
    </UserContext.Provider>
  );
};

export { UserContext, UserProvider };
