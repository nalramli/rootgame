import { Badge, Group, Paper, Stack, Text, Tooltip } from "@mantine/core";
import type { components } from "../../../api/types";
import { MOOD_DATA } from "../../../data/ratsMoodData";
import { getItemIcon } from "../../../utils/itemIcons";

const COMMAND_ITEMS = ["Boots", "Bag", "Coin"];
const PROWESS_ITEMS = ["Hammer", "Tea", "Sword", "Crossbow"];

// The value printed below each slot (slot 1→2, slot 2→2, slot 3→3, slot 4→4).
const SLOT_VALUES = [2, 2, 3, 4];

type MoodType = components["schemas"]["ValidMoodsEnum"];

function ValueLabel({ value, active }: { value: number; active: boolean }) {
  if (active) {
    return (
      <div
        style={{
          width: 20,
          height: 20,
          borderRadius: "50%",
          backgroundColor: "#8B0000",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <Text size="xs" fw={900} c="white" lh={1}>
          {value}
        </Text>
      </div>
    );
  }
  return (
    <Text size="xs" fw={700} c="dimmed">
      {value}
    </Text>
  );
}

interface HoardTrackProps {
  label: string;
  items: { item: { value: string; label: string } }[];
  /** Labels of items that can fill this track, e.g. ["Boots", "Bag", "Coin"] */
  trackItems: string[];
}

function HoardTrack({ label, items, trackItems }: HoardTrackProps) {
  // Which position is active: 0 = base slot, 1–4 = item slots
  const activeIndex = items.length; // 0 items → base active; 1 item → slot 0 active; etc.

  return (
    <div style={{ position: "relative", paddingTop: "6px" }}>
      <div
        style={{
          border: "1px solid var(--mantine-color-gray-3)",
          borderRadius: "8px",
          padding: "12px",
          backgroundColor: "white",
          boxShadow: "0 1px 3px rgba(0, 0, 0, 0.05)",
          position: "relative",
        }}
      >
        {/* Floating label — top left */}
        <Tooltip
          label={`Accepts: ${trackItems.join(", ")}`}
          withArrow
          position="top"
        >
          <Text
            size="xs"
            fw={700}
            c="dimmed"
            tt="uppercase"
            style={{
              position: "absolute",
              top: "-8px",
              left: "12px",
              backgroundColor: "#f5ead6",
              paddingRight: "6px",
              paddingLeft: "6px",
              cursor: "help",
            }}
          >
            {label}
          </Text>
        </Tooltip>

        {/* Slots row: base box + 4 item slots */}
        <Group gap="xs" justify="center" mt={4} wrap="nowrap">
          {/* Base slot — always filled, represents the starting value of 1 */}
          <Stack align="center" gap={4}>
            <Paper
              w={52}
              h={52}
              withBorder
              radius="md"
              style={{
                backgroundColor: "#f5e6e6",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                borderColor: "#8B0000",
              }}
            />
            <ValueLabel value={1} active={activeIndex === 0} />
          </Stack>

          {/* Item slots */}
          {SLOT_VALUES.map((slotValue, index) => {
            const item = items[index];
            const isFilled = index < items.length;
            const isActive = index + 1 === activeIndex;

            return (
              <Stack key={index} align="center" gap={4}>
                <Tooltip
                  label={
                    isFilled
                      ? item.item.label
                      : `Accepts: ${trackItems.join(", ")}`
                  }
                  withArrow
                  position="top"
                >
                  <Paper
                    w={52}
                    h={52}
                    withBorder
                    radius="md"
                    style={{
                      backgroundColor: isFilled
                        ? "#f5e6e6"
                        : "var(--mantine-color-gray-2)",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      borderColor: isFilled
                        ? "#8B0000"
                        : "var(--mantine-color-gray-4)",
                      cursor: "help",
                      flexWrap: "wrap",
                      gap: 2,
                      padding: 4,
                    }}
                  >
                    {isFilled ? (
                      getItemIcon(item.item.label, 26)
                    ) : (
                      <div
                        style={{
                          display: "flex",
                          flexWrap: "wrap",
                          gap: 1,
                          alignItems: "center",
                          justifyContent: "center",
                          opacity: 0.25,
                        }}
                      >
                        {trackItems.map((name) => (
                          <span key={name}>{getItemIcon(name, 25)}</span>
                        ))}
                      </div>
                    )}
                  </Paper>
                </Tooltip>
                <ValueLabel value={slotValue} active={isActive} />
              </Stack>
            );
          })}
        </Group>
      </div>
    </div>
  );
}

function moodTooltipContent(moodType: MoodType, blocked?: boolean) {
  const data = MOOD_DATA[moodType];
  return (
    <Stack gap={4}>
      <Text size="xs" fw={700}>
        {data.label}
        {data.item ? ` (${data.item})` : ""}
      </Text>
      <Text size="xs">{data.description}</Text>
      {blocked && (
        <Text size="xs" c="red.4" fw={600}>
          Blocked — item in Hoard
        </Text>
      )}
    </Stack>
  );
}

function MoodBadge({
  moodType,
  isCurrent,
}: {
  moodType: MoodType;
  isCurrent: boolean;
}) {
  return (
    <Tooltip
      label={moodTooltipContent(moodType)}
      multiline
      w={260}
      withArrow
      position="top"
    >
      <Badge
        size="md"
        variant={isCurrent ? "filled" : "light"}
        style={{
          backgroundColor: isCurrent ? "#8B0000" : undefined,
          color: isCurrent ? "white" : "#8B0000",
          cursor: "help",
          textTransform: "capitalize",
          border: isCurrent ? undefined : "1px solid #8B0000",
        }}
      >
        {isCurrent
          ? `★ ${MOOD_DATA[moodType].label}`
          : MOOD_DATA[moodType].label}
      </Badge>
    </Tooltip>
  );
}

interface RatsHoardSectionProps {
  commandItems: components["schemas"]["CommandItemEntry"][];
  prowessItems: components["schemas"]["ProwessItemEntry"][];
  mood: components["schemas"]["CurrentMood"];
  validMoods: components["schemas"]["ValidMoodsEnum"][];
}

export default function RatsHoardSection({
  commandItems,
  prowessItems,
  mood,
  validMoods,
}: RatsHoardSectionProps) {
  const currentMood = mood.mood_type as MoodType;
  const otherMoods: MoodType[] = [
    "bitter",
    "grandiose",
    "jubilant",
    "lavish",
    "relentless",
    "rowdy",
    "stubborn",
    "wrathful",
  ].filter((m) => m !== currentMood) as MoodType[];

  return (
    <div style={{ position: "relative", paddingTop: "6px" }}>
      <div
        style={{
          border: "1px solid var(--mantine-color-gray-3)",
          borderRadius: "8px",
          padding: "12px",
          backgroundColor: "white",
          boxShadow: "0 1px 3px rgba(0, 0, 0, 0.05)",
          position: "relative",
        }}
      >
        <Text
          size="xs"
          fw={700}
          c="dimmed"
          tt="uppercase"
          style={{
            position: "absolute",
            top: "-8px",
            left: "50%",
            transform: "translateX(-50%)",
            backgroundColor: "#f5ead6",
            paddingRight: "6px",
            paddingLeft: "6px",
          }}
        >
          The Hoard
        </Text>

        <Stack gap="sm" mt={4}>
          <HoardTrack
            label="Command"
            items={commandItems}
            trackItems={COMMAND_ITEMS}
          />
          <HoardTrack
            label="Prowess"
            items={prowessItems}
            trackItems={PROWESS_ITEMS}
          />

          {/* Mood display */}
          <div style={{ position: "relative", paddingTop: "6px" }}>
            <div
              style={{
                border: "1px solid var(--mantine-color-gray-3)",
                borderRadius: "8px",
                padding: "10px 12px",
                backgroundColor: "#fdf6f0",
                position: "relative",
              }}
            >
              <Text
                size="xs"
                fw={700}
                c="dimmed"
                tt="uppercase"
                style={{
                  position: "absolute",
                  top: "-8px",
                  left: "50%",
                  transform: "translateX(-50%)",
                  backgroundColor: "#f5ead6",
                  paddingRight: "6px",
                  paddingLeft: "6px",
                }}
              >
                Mood Card
              </Text>

              <Stack gap="xs" mt={2}>
                {/* Current mood — own row */}
                <Group justify="center">
                  <MoodBadge moodType={currentMood} isCurrent={true} />
                </Group>

                {/* All other moods */}
                <Group gap="xs" justify="center" wrap="wrap">
                  {otherMoods.map((m) => {
                    const isAvailable = validMoods.includes(m);
                    if (!isAvailable) {
                      return (
                        <Tooltip
                          key={m}
                          label={moodTooltipContent(m, true)}
                          multiline
                          w={260}
                          withArrow
                          position="top"
                        >
                          <Badge
                            size="md"
                            variant="outline"
                            style={{
                              opacity: 0.35,
                              cursor: "help",
                              textTransform: "capitalize",
                              borderColor: "var(--mantine-color-gray-4)",
                              color: "var(--mantine-color-gray-6)",
                            }}
                          >
                            {MOOD_DATA[m].label}
                          </Badge>
                        </Tooltip>
                      );
                    }
                    return <MoodBadge key={m} moodType={m} isCurrent={false} />;
                  })}
                </Group>
              </Stack>
            </div>
          </div>
        </Stack>
      </div>
    </div>
  );
}
