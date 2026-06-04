import { useContext, useEffect, useMemo } from "react";

export type Point = { x: number; y: number };

export type Link = { from: string; to: string };
import {
  buildingSlotMap,
  suitMap,
  warriorSlotMap,
  tokenSlotMap,
  defaultPositions,
  defaultLinks,
  waterLinks,
  burrowPosition,
} from "../../data/autumn_map";
import { Clearing, type ClearingProps } from "./Clearing";
import { Path } from "./Path";
import { BuildingSlot } from "./BuildingSlot";
import { WarriorSlot } from "./WarriorSlot";
import { TokenSlot } from "./TokenSlot";
import useWarriorTable from "../../hooks/useWarriorTable";
import useTokenTable from "../../hooks/useTokenTable";
import useBuildingTable from "../../hooks/useBuildingTable";
import { type FactionLabel } from "../../utils/factionUtils";
import { useTurnInfoQuery } from "../../hooks/useTurnInfoQuery";
import { GameContext } from "../../contexts/GameProvider";
import { Paper } from "@mantine/core";

import { useClearingsQuery } from "../../hooks/useClearingsQuery";
import type { BuildingType } from "./BuildingSlot";
import { useCrowPlayerQuery } from "../../hooks/useCrowPlayerQuery";
import useRatsPlayerQuery from "../../hooks/useRatsPlayerQuery";

// Board component: positions, nodes, links, simple viewbox scaling
export default function SvgBoard({
  mapName = "autumn",
  width = 800,
  height = 800,
}: {
  mapName?: "autumn";
  width?: number;
  height?: number;
}) {
  const { gameId, session } = useContext(GameContext);
  const isGameStarted = session?.status?.label !== "Not Started" && !!session;
  const isTurnTrackingActive = session?.status?.label === "Setup Completed";

  const factionList: FactionLabel[] = useMemo(() => {
    if (!session?.players) return [];
    return session.players.map(
      (p) => p.faction.label as FactionLabel,
    ) as FactionLabel[];
  }, [session?.players]);

  const turnInfo = useTurnInfoQuery(gameId as number, isTurnTrackingActive);
  const { data: clearingsData } = useClearingsQuery(
    gameId as number,
    isGameStarted,
  );
  const isCrowsInGame = factionList.includes("Crows");
  const { privateInfo } = useCrowPlayerQuery(
    gameId as number,
    isGameStarted && isCrowsInGame,
  );

  const isMolesInGame = factionList.includes("Moles");
  const isRatsInGame = factionList.includes("Rats");

  const { publicInfo: ratsPublicInfo } = useRatsPlayerQuery(
    gameId as number,
    isRatsInGame && isGameStarted,
  );

  useEffect(() => {
    if (!turnInfo.data) return;
    console.log(turnInfo.data);
  }, [turnInfo.data]);

  const { warriorTable } = useWarriorTable(
    gameId as number,
    factionList,
    isGameStarted,
  );

  const { tokenTable } = useTokenTable(
    gameId as number,
    factionList,
    isGameStarted,
  );

  const accumulatedTokens: Record<
    number,
    { faction: FactionLabel; tokenType: string; count: number }[]
  > = useMemo(() => {
    const map: Record<
      number,
      { faction: FactionLabel; tokenType: string; count: number }[]
    > = {};
    for (const token of tokenTable) {
      if (!token.clearing_number) continue;
      if (!map[token.clearing_number]) {
        map[token.clearing_number] = [];
      }
      const sameTokenTypeIdx = map[token.clearing_number].findIndex(
        (t) => t.tokenType === token.tokenType,
      );
      if (sameTokenTypeIdx === -1) {
        map[token.clearing_number].push({
          faction: token.faction as FactionLabel,
          tokenType: token.tokenType,
          count: 1,
        });
      } else {
        map[token.clearing_number][sameTokenTypeIdx].count += 1;
      }
    }
    return map;
  }, [tokenTable]);

  const { buildingTable, isSuccess: isSuccessBuilding } = useBuildingTable(
    gameId as number,
    factionList,
    isGameStarted,
  );

  const buildingInfoByClearingAndSlot = useMemo(() => {
    return (clearingNumber: number, slot: number) => {
      const b = buildingTable.find(
        (b) => b.clearing_number === clearingNumber && b.building_slot === slot,
      );
      if (!b) {
        // check for ruins
        const ruins = clearingsData?.find(
          (c) => c.clearing_number === clearingNumber,
        )?.ruins;
        if (ruins?.includes(slot)) {
          return {
            buildingType: "ruin" as BuildingType,
            faction: "Neutral" as any,
          };
        }
        return null;
      }
      return {
        buildingType: b.buildingType,
        faction: b.faction as FactionLabel,
      };
    };
  }, [buildingTable, isSuccessBuilding, clearingsData]);

  const clearingProps: ClearingProps[] = useMemo(() => {
    return defaultPositions.map((pos, i) => {
      const clearingNumber = i + 1;
      const suit = suitMap[clearingNumber];
      return {
        clearingNumber,
        suit,
        circleProps: {
          cx: pos.x * width,
          cy: pos.y * height,
          r: height * 0.09,
        },
      };
    });
  }, [mapName, width, height]);

  // create list of paths
  const pathList = useMemo(() => {
    return defaultLinks.map((link) => {
      const a = defaultPositions[link.from - 1];
      const b = defaultPositions[link.to - 1];
      const aScaled = { x: a.x * width, y: a.y * height };
      const bScaled = { x: b.x * width, y: b.y * height };
      return {
        a: aScaled,
        b: bScaled,
        stroke: "brown",
      };
    });
  }, [mapName, width, height]);

  const waterPathList = useMemo(() => {
    return waterLinks.map((link) => {
      const a = defaultPositions[link.from - 1];
      const b = defaultPositions[link.to - 1];
      const aScaled = { x: a.x * width, y: a.y * height };
      const bScaled = { x: b.x * width, y: b.y * height };
      return {
        a: aScaled,
        b: bScaled,
        stroke: "blue",
      };
    });
  }, [mapName, width, height]);

  const burrowWarriorCount = isMolesInGame
    ? warriorTable?.filter(
        (e) => e.faction === "Moles" && e.clearing_number === 0,
      ).length ?? 0
    : 0;

  const burrowClearingProp = isMolesInGame
    ? {
        clearingNumber: 0,
        suit: "#d49d99",
        circleProps: {
          cx: width * burrowPosition.x,
          cy: height * burrowPosition.y,
          r: height * burrowPosition.radiusScale,
        },
        label: "B",
        tooltip: "The Burrow — adjacent to all tunnel clearings",
      }
    : null;

  return (
    <Paper
      shadow="xl"
      p="md"
      radius="md"
      withBorder
      style={{ width: "100%", height: "100%", boxSizing: "border-box" }}
    >
      <svg
        viewBox={`${width * 0.15} ${height * 0.08} ${width * 0.7} ${height * 0.88}`}
        style={{ width: "100%", height: "100%", display: "block" }}
      >
        <defs>
          <filter id="shadow" x="-50%" y="-50%" width="200%" height="200%">
            <feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.2" />
          </filter>
        </defs>
        <g stroke="black" fill="white" filter="url(#shadow)">
          {pathList.map((l, i) => {
            return <Path key={i} a={l.a} b={l.b} stroke={l.stroke} />;
          })}
          {waterPathList.map((l, i) => {
            return (
              <Path
                key={i}
                a={l.a}
                b={l.b}
                stroke={l.stroke}
                strokeWidth={10}
              />
            );
          })}
          {clearingProps.map((clearingProp, idx) => (
            <Clearing key={idx} {...clearingProp}>
              {buildingSlotMap[clearingProp.clearingNumber]?.map((s, idx) => {
                const info = buildingInfoByClearingAndSlot(
                  clearingProp.clearingNumber,
                  idx,
                );
                let tooltip = undefined;
                if (info) {
                  // Special case for types that don't just end in 's' or singularizing logic
                  const formattedType =
                    info.buildingType === "base"
                      ? "Base"
                      : info.buildingType === "ruin"
                        ? "Ruin"
                        : info.buildingType.charAt(0).toUpperCase() +
                          info.buildingType.slice(1).replace(/s$/, "");

                  tooltip =
                    info.buildingType === "ruin"
                      ? "Ruin"
                      : `${info.faction} ${formattedType}`;
                }
                return (
                  <BuildingSlot
                    key={`b-${idx}`}
                    {...s}
                    buildingInfo={info}
                    tooltip={tooltip}
                  />
                );
              })}
              {factionList?.map((faction: FactionLabel, idx) => {
                const warriorCount =
                  warriorTable?.filter(
                    (entry) =>
                      entry.faction === faction &&
                      entry.clearing_number === clearingProp.clearingNumber,
                  ).length ?? 0;
                const warlordHere =
                  faction === "Rats" &&
                  ratsPublicInfo?.warlord.clearing_number ===
                    clearingProp.clearingNumber;
                const count = warlordHere ? warriorCount + 1 : warriorCount;
                const tooltip =
                  count > 0
                    ? warlordHere
                      ? `Rats Warriors (${warriorCount}) + Warlord`
                      : `${faction} Warriors (${count})`
                    : undefined;
                return (
                  <WarriorSlot
                    key={`w-${idx}`}
                    {...warriorSlotMap[clearingProp.clearingNumber][idx]}
                    warriorInfo={{
                      faction: faction,
                      count: count,
                      hasWarlord: warlordHere,
                    }}
                    tooltip={tooltip}
                  />
                );
              })}
              {accumulatedTokens[clearingProp.clearingNumber]?.map((t, idx) => {
                let tooltip = undefined;
                if (t.faction === "Crows" && t.tokenType === "?") {
                  const privatePlot = privateInfo?.facedown_plots?.find(
                    (p) =>
                      p.clearing_number === clearingProp.clearingNumber &&
                      p.is_facedown,
                  );
                  if (privatePlot) {
                    tooltip = `Facedown Plot: ${
                      privatePlot.plot_type.charAt(0).toUpperCase() +
                      privatePlot.plot_type.slice(1)
                    }`;
                  } else {
                    tooltip = "Facedown Plot";
                  }
                } else {
                  const tokenLabel =
                    t.tokenType.charAt(0).toUpperCase() + t.tokenType.slice(1);
                  tooltip = `${t.faction} ${tokenLabel}${t.count > 1 ? ` (${t.count})` : ""}`;
                }
                return (
                  <TokenSlot
                    key={`t-${idx}`}
                    {...tokenSlotMap[clearingProp.clearingNumber][idx]}
                    tokenInfo={{
                      faction: t.faction,
                      tokenType: t.tokenType,
                      count: t.count,
                    }}
                    tooltip={tooltip}
                  />
                );
              })}
            </Clearing>
          ))}
          {isMolesInGame && burrowClearingProp && (
            <Clearing {...burrowClearingProp}>
              <WarriorSlot
                {...warriorSlotMap[0][0]}
                warriorInfo={{
                  faction: "Moles",
                  count: burrowWarriorCount,
                }}
                tooltip={
                  burrowWarriorCount > 0
                    ? `Moles Warriors (${burrowWarriorCount})`
                    : undefined
                }
              />
            </Clearing>
          )}
        </g>
      </svg>
    </Paper>
  );
}
