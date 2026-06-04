import {
  Container,
  Tabs,
  Title,
  Table,
  Button,
  Stack,
  Select,
  Text,
  Badge,
  Paper,
  Group,
  ActionIcon,
  Modal,
} from "@mantine/core";
import {
  useActiveGames,
  useJoinableGames,
  useCreateGame,
  useJoinGame,
  useDeleteGame,
  type GameListItem,
} from "../hooks/useGames";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  IconPlus,
  IconExternalLink,
  IconUserPlus,
  IconLogout,
  IconTrash,
} from "@tabler/icons-react";
import { useContext } from "react";
import { UserContext } from "../contexts/UserProvider";
import DemoUserSwitch from "../components/DemoUserSwitch";
import DemoQuickStart from "../components/DemoQuickStart";

const LobbyPage = () => {
  const navigate = useNavigate();
  const { signOut, username } = useContext(UserContext);
  const { data: activeGames } = useActiveGames();
  const { data: joinableGames } = useJoinableGames();
  const createGameMutation = useCreateGame();
  const joinGameMutation = useJoinGame();
  const deleteGameMutation = useDeleteGame();

  const [map, setMap] = useState("0");
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const handleCreateGame = async () => {
    createGameMutation.mutate(
      { map_label: map },
      {
        onSuccess: async (data) => {
          await joinGameMutation.mutateAsync(data.game_id);
          navigate(`/game/${data.game_id}`);
        },
      },
    );
  };

  const handleJoinGame = async (gameId: number) => {
    await joinGameMutation.mutateAsync(gameId);
    navigate(`/game/${gameId}`);
  };

  const GameTable = ({
    games,
    type,
  }: {
    games: GameListItem[] | undefined;
    type: "active" | "joinable";
  }) => {
    if (!games || games.length === 0) {
      return (
        <Text ta="center" py="xl">
          No games found.
        </Text>
      );
    }

    return (
      <Table striped highlightOnHover verticalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>ID</Table.Th>
            <Table.Th>Owner</Table.Th>
            <Table.Th>Players</Table.Th>
            <Table.Th>Status</Table.Th>
            <Table.Th>Action</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {games.map((game) => (
            <Table.Tr key={game.id}>
              <Table.Td>{game.id}</Table.Td>
              <Table.Td>{game.owner_username}</Table.Td>
              <Table.Td>{game.player_count}</Table.Td>
              <Table.Td>
                <Badge variant="light">{game.status.label}</Badge>
              </Table.Td>
              <Table.Td>
                {type === "active" ? (
                  <Group gap="xs">
                    <Button
                      leftSection={<IconExternalLink size={14} />}
                      size="xs"
                      onClick={() => navigate(`/game/${game.id}`)}
                    >
                      Open
                    </Button>
                    {game.owner_username === username && (
                      <ActionIcon
                        color="red"
                        variant="subtle"
                        size="sm"
                        aria-label="Delete game"
                        onClick={() => setConfirmDeleteId(game.id)}
                      >
                        <IconTrash size={14} />
                      </ActionIcon>
                    )}
                  </Group>
                ) : (
                  <Button
                    leftSection={<IconUserPlus size={14} />}
                    size="xs"
                    color="green"
                    onClick={() => handleJoinGame(game.id)}
                    loading={
                      joinGameMutation.isPending &&
                      joinGameMutation.variables === game.id
                    }
                  >
                    Join
                  </Button>
                )}
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    );
  };

  return (
    <Container size="lg" py="xl">
      <Group justify="space-between" align="center" mb="xl">
        <Title order={1}>Game Lobby</Title>
        <Group>
          <DemoUserSwitch />
          <Text size="sm" fw={500}>
            Logged in as: {username}
          </Text>
          <Button
            variant="subtle"
            color="red"
            leftSection={<IconLogout size={16} />}
            onClick={() => signOut()}
          >
            Logout
          </Button>
        </Group>
      </Group>

      <Tabs defaultValue="active">
        <Tabs.List mb="md">
          <Tabs.Tab value="active">Active Games</Tabs.Tab>
          <Tabs.Tab value="joinable">Games to Join</Tabs.Tab>
          <Tabs.Tab value="create">Create a Game</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="active">
          <GameTable games={activeGames} type="active" />
        </Tabs.Panel>

        <Tabs.Panel value="joinable">
          <GameTable games={joinableGames} type="joinable" />
        </Tabs.Panel>

        <Tabs.Panel value="create">
          <Stack gap="md">
            <DemoQuickStart />
            <Paper withBorder p="md" radius="md">
              <Stack>
                <Title order={3}>Start a New Game</Title>
                <Select
                  label="Select Map"
                  data={[{ value: "0", label: "Autumn" }]}
                  value={map}
                  onChange={(val) => setMap(val || "0")}
                />
                <Button
                  leftSection={<IconPlus size={14} />}
                  onClick={handleCreateGame}
                  loading={createGameMutation.isPending}
                >
                  Create Game
                </Button>
              </Stack>
            </Paper>
          </Stack>
        </Tabs.Panel>
      </Tabs>
      <Modal
        opened={confirmDeleteId !== null}
        onClose={() => setConfirmDeleteId(null)}
        title="Delete game"
        centered
      >
        <Text mb="lg">
          Are you sure you want to delete game #{confirmDeleteId}? This cannot
          be undone.
        </Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setConfirmDeleteId(null)}>
            Cancel
          </Button>
          <Button
            color="red"
            loading={deleteGameMutation.isPending}
            onClick={() => {
              if (confirmDeleteId !== null) {
                deleteGameMutation.mutate(confirmDeleteId, {
                  onSuccess: () => setConfirmDeleteId(null),
                });
              }
            }}
          >
            Delete
          </Button>
        </Group>
      </Modal>
    </Container>
  );
};

export default LobbyPage;
