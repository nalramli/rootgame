import { Stack, Text, Tooltip, Box, Title, ScrollArea } from "@mantine/core";

export default function RatsTurnFlow() {
  return (
    <ScrollArea h={350} offsetScrollbars p="xs">
      <Stack gap="sm">
        {/* Birdsong */}
        <Box>
          <Box bg="orange.6" p="xs" mb="xs" style={{ borderRadius: "4px" }}>
            <Title order={4} c="white" tt="uppercase">
              Birdsong
            </Title>
          </Box>
          <Stack gap={4}>
            <Tooltip
              label="At each mob, remove all enemy buildings and tokens, take an item from ruin if any, and remove the ruin if it's empty. After resolving all mobs, roll the mob die once and place a mob in a matching clearing with no mob but adjacent to one."
              withArrow
              multiline
              w={280}
            >
              <Text size="sm" fw={600} style={{ cursor: "help" }}>
                1st: Raze
              </Text>
            </Tooltip>

            <Tooltip
              label="Recruit warriors equal to Prowess in your warlord's clearing, then one warrior at each stronghold."
              withArrow
              multiline
              w={260}
            >
              <Text size="sm" fw={600} style={{ cursor: "help" }}>
                2nd: Recruit
              </Text>
            </Tooltip>

            <Tooltip
              label="Anoint warlord if it is off the map: Replace a Hundreds warrior with your warlord. If you cannot, place your warlord in any clearing."
              withArrow
              multiline
              w={270}
            >
              <Text size="sm" fw={600} style={{ cursor: "help" }}>
                3rd: Anoint
              </Text>
            </Tooltip>

            <Tooltip
              label="Choose a different mood that does not show an item in your Hoard. If you cannot, choose Lavish."
              withArrow
              multiline
              w={260}
            >
              <Text size="sm" fw={600} style={{ cursor: "help" }}>
                4th: Choose a different mood
              </Text>
            </Tooltip>
          </Stack>
        </Box>

        {/* Daylight */}
        <Box>
          <Box bg="blue.4" p="xs" mb="xs" style={{ borderRadius: "4px" }}>
            <Title order={4} c="white" tt="uppercase">
              Daylight
            </Title>
          </Box>
          <Stack gap={4}>
            <Tooltip label="Craft using strongholds." withArrow>
              <Text size="sm" fw={600} style={{ cursor: "help" }}>
                1st: Craft
              </Text>
            </Tooltip>

            <Tooltip
              label="Take a number of actions up to your Command value."
              withArrow
              multiline
              w={240}
            >
              <Text size="sm" fw={600} style={{ cursor: "help" }}>
                2nd: Command the Hundreds (×Command)
              </Text>
            </Tooltip>

            <Stack gap={2} pl="sm">
              <Tooltip
                label="Move your warriors from one clearing to an adjacent clearing."
                withArrow
                multiline
                w={240}
              >
                <Text size="xs" fw={500} style={{ cursor: "help" }}>
                  • Move
                </Text>
              </Tooltip>
              <Tooltip label="Initiate a battle in a clearing." withArrow>
                <Text size="xs" fw={500} style={{ cursor: "help" }}>
                  • Battle
                </Text>
              </Tooltip>
              <Tooltip
                label="Spend a card to place a stronghold in a matching clearing you rule."
                withArrow
                multiline
                w={240}
              >
                <Text size="xs" fw={500} style={{ cursor: "help" }}>
                  • Build
                </Text>
              </Tooltip>
            </Stack>

            <Tooltip
              label="Take a number of Advance actions up to your Prowess value. Each Advance: move your warlord with any Hundreds warriors, then battle in your warlord's clearing."
              withArrow
              multiline
              w={280}
            >
              <Text size="sm" fw={600} style={{ cursor: "help" }}>
                3rd: Advance the Warlord (×Prowess)
              </Text>
            </Tooltip>
          </Stack>
        </Box>

        {/* Evening */}
        <Box>
          <Box bg="indigo.4" p="xs" mb="xs" style={{ borderRadius: "4px" }}>
            <Title order={4} c="white" tt="uppercase">
              Evening
            </Title>
          </Box>
          <Stack gap={4}>
            <Tooltip
              label="Spend a card to place a mob in a matching clearing with a Hundreds warrior (including your warlord) but no mob."
              withArrow
              multiline
              w={260}
            >
              <Text size="sm" fw={600} style={{ cursor: "help" }}>
                1st: Incite (any number of times)
              </Text>
            </Tooltip>

            <Tooltip
              label="Score VP for clearings you rule that have a Hundreds piece and no enemy pieces. 1–2: +1 VP, 3–4: +2 VP, 5: +3 VP, 6+: +4 VP."
              withArrow
              multiline
              w={270}
            >
              <Text size="sm" fw={600} style={{ cursor: "help" }}>
                2nd: Oppress
              </Text>
            </Tooltip>

            <Tooltip
              label="Draw 1 card. Discard down to 5 cards."
              withArrow
            >
              <Text size="sm" fw={600} style={{ cursor: "help" }}>
                3rd: Draw 1 / Discard to 5
              </Text>
            </Tooltip>
          </Stack>
        </Box>
      </Stack>
    </ScrollArea>
  );
}
