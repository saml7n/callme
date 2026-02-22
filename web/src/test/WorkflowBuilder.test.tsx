/**
 * Unit tests for the workflow builder.
 *
 * React Flow requires a DOM container with non-zero dimensions, so we mock
 * the resize observer and test through the builder's serialisation and
 * validation logic, plus component rendering.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { ReactFlowProvider } from '@xyflow/react'
import '@xyflow/react/dist/style.css'

// Mock ResizeObserver (React Flow needs it — must be a class/constructor)
class MockResizeObserver {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}

beforeEach(() => {
  global.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver
  // Mock getBoundingClientRect for React Flow
  Element.prototype.getBoundingClientRect = vi.fn(() => ({
    width: 1000,
    height: 800,
    top: 0,
    left: 0,
    bottom: 800,
    right: 1000,
    x: 0,
    y: 0,
    toJSON: () => {},
  }))
})

/** Wrap component in ReactFlowProvider (needed by Handle). */
function FlowWrapper({ children }: { children: React.ReactNode }) {
  return <ReactFlowProvider>{children}</ReactFlowProvider>
}

// ---------------------------------------------------------------------------
// Tests for individual components
// ---------------------------------------------------------------------------

describe('ConversationNode', () => {
  it('renders with instructions preview', async () => {
    const { default: ConversationNode } = await import(
      '@/components/nodes/ConversationNode'
    )

    render(
      <ConversationNode
        id="test"
        type="conversation"
        data={{
          label: 'greeting',
          instructions: 'Welcome the caller warmly.',
          examples: [],
          max_iterations: 5,
          isEntry: true,
        }}
        selected={false}
        isConnectable={true}
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        zIndex={0}
        dragging={false}
        deletable={true}
        selectable={true}
        parentId=""
        sourcePosition={undefined}
        targetPosition={undefined}
        dragHandle=""
      />,
      { wrapper: FlowWrapper },
    )

    expect(screen.getByText('greeting')).toBeInTheDocument()
    expect(screen.getByText('Welcome the caller warmly.')).toBeInTheDocument()
    expect(screen.getByText('Start')).toBeInTheDocument()
    expect(screen.getByText('max 5 turns')).toBeInTheDocument()
  })

  it('shows "No instructions set" when empty', async () => {
    const { default: ConversationNode } = await import(
      '@/components/nodes/ConversationNode'
    )

    render(
      <ConversationNode
        id="test"
        type="conversation"
        data={{ label: 'empty', instructions: '', isEntry: false }}
        selected={false}
        isConnectable={true}
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        zIndex={0}
        dragging={false}
        deletable={true}
        selectable={true}
        parentId=""
        sourcePosition={undefined}
        targetPosition={undefined}
        dragHandle=""
      />,
      { wrapper: FlowWrapper },
    )

    expect(screen.getByText('No instructions set')).toBeInTheDocument()
  })
})

describe('DecisionNode', () => {
  it('renders with instruction preview', async () => {
    const { default: DecisionNode } = await import(
      '@/components/nodes/DecisionNode'
    )

    render(
      <DecisionNode
        id="test"
        type="decision"
        data={{
          label: 'router',
          instruction: 'Route based on the caller intent.',
          isEntry: false,
        }}
        selected={false}
        isConnectable={true}
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        zIndex={0}
        dragging={false}
        deletable={true}
        selectable={true}
        parentId=""
        sourcePosition={undefined}
        targetPosition={undefined}
        dragHandle=""
      />,
      { wrapper: FlowWrapper },
    )

    expect(screen.getByText('router')).toBeInTheDocument()
    expect(screen.getByText('Route based on the caller intent.')).toBeInTheDocument()
    expect(screen.getByText('Decision')).toBeInTheDocument()
  })
})

describe('ActionNode', () => {
  it('renders end_call type', async () => {
    const { default: ActionNode } = await import(
      '@/components/nodes/ActionNode'
    )

    render(
      <ActionNode
        id="test"
        type="action"
        data={{
          label: 'hangup',
          action_type: 'end_call',
          message: 'Goodbye, have a great day!',
          isEntry: false,
        }}
        selected={false}
        isConnectable={true}
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        zIndex={0}
        dragging={false}
        deletable={true}
        selectable={true}
        parentId=""
        sourcePosition={undefined}
        targetPosition={undefined}
        dragHandle=""
      />,
      { wrapper: FlowWrapper },
    )

    expect(screen.getByText('hangup')).toBeInTheDocument()
    expect(screen.getByText('End Call')).toBeInTheDocument()
    expect(screen.getByText('Goodbye, have a great day!')).toBeInTheDocument()
    expect(screen.getByText('Terminates the call')).toBeInTheDocument()
  })

  it('renders transfer type with target number', async () => {
    const { default: ActionNode } = await import(
      '@/components/nodes/ActionNode'
    )

    render(
      <ActionNode
        id="test"
        type="action"
        data={{
          label: 'xfer',
          action_type: 'transfer',
          announcement: 'Transferring you now.',
          target_number: '+447700900000',
          isEntry: false,
        }}
        selected={false}
        isConnectable={true}
        positionAbsoluteX={0}
        positionAbsoluteY={0}
        zIndex={0}
        dragging={false}
        deletable={true}
        selectable={true}
        parentId=""
        sourcePosition={undefined}
        targetPosition={undefined}
        dragHandle=""
      />,
      { wrapper: FlowWrapper },
    )

    expect(screen.getByText('Transfer')).toBeInTheDocument()
    expect(screen.getByText('Transferring you now.')).toBeInTheDocument()
    expect(screen.getByText('+447700900000')).toBeInTheDocument()
  })
})

describe('NodePalette', () => {
  it('renders all three draggable node types', async () => {
    const { default: NodePalette } = await import('@/components/NodePalette')

    render(<NodePalette />)

    expect(screen.getByText('Conversation')).toBeInTheDocument()
    expect(screen.getByText('Decision')).toBeInTheDocument()
    expect(screen.getByText('Action')).toBeInTheDocument()
  })
})

describe('ConfigPanel', () => {
  it('shows conversation config with instructions textarea', async () => {
    const { default: ConfigPanel } = await import('@/components/ConfigPanel')

    const mockNode = {
      id: 'conv1',
      type: 'conversation',
      position: { x: 0, y: 0 },
      data: {
        label: 'greeting',
        instructions: 'Hello caller',
        examples: [],
        max_iterations: 10,
      },
    }

    render(
      <ConfigPanel
        node={mockNode as any}
        entryNodeId="conv1"
        onUpdateNode={vi.fn()}
        onSetEntry={vi.fn()}
        onDeleteNode={vi.fn()}
      />,
    )

    expect(screen.getByText('Configure Node')).toBeInTheDocument()
    expect(screen.getByText('Instructions')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Hello caller')).toBeInTheDocument()
    expect(screen.getByText('This is the entry node')).toBeInTheDocument()
  })

  it('shows action config with action_type dropdown', async () => {
    const { default: ConfigPanel } = await import('@/components/ConfigPanel')

    const mockNode = {
      id: 'act1',
      type: 'action',
      position: { x: 0, y: 0 },
      data: {
        label: 'hangup',
        action_type: 'end_call',
        message: 'Goodbye!',
      },
    }

    render(
      <ConfigPanel
        node={mockNode as any}
        entryNodeId="other"
        onUpdateNode={vi.fn()}
        onSetEntry={vi.fn()}
        onDeleteNode={vi.fn()}
      />,
    )

    expect(screen.getByText('Action Type')).toBeInTheDocument()
    expect(screen.getByText('Closing Message')).toBeInTheDocument()
    // The "Set as Entry" button should appear since this isn't the entry node
    expect(screen.getByText('Set as Entry')).toBeInTheDocument()
  })

  it('calls onDeleteNode when delete button clicked', async () => {
    const { default: ConfigPanel } = await import('@/components/ConfigPanel')
    const user = userEvent.setup()

    const onDeleteNode = vi.fn()
    const mockNode = {
      id: 'n1',
      type: 'conversation',
      position: { x: 0, y: 0 },
      data: { label: 'x', instructions: '' },
    }

    render(
      <ConfigPanel
        node={mockNode as any}
        entryNodeId=""
        onUpdateNode={vi.fn()}
        onSetEntry={vi.fn()}
        onDeleteNode={onDeleteNode}
      />,
    )

    await user.click(screen.getByText('Delete Node'))
    expect(onDeleteNode).toHaveBeenCalledWith('n1')
  })

  it('calls onSetEntry when set-as-entry button clicked', async () => {
    const { default: ConfigPanel } = await import('@/components/ConfigPanel')
    const user = userEvent.setup()

    const onSetEntry = vi.fn()
    const mockNode = {
      id: 'n2',
      type: 'decision',
      position: { x: 0, y: 0 },
      data: { label: 'router', instruction: '' },
    }

    render(
      <ConfigPanel
        node={mockNode as any}
        entryNodeId="other"
        onUpdateNode={vi.fn()}
        onSetEntry={onSetEntry}
        onDeleteNode={vi.fn()}
      />,
    )

    await user.click(screen.getByText('Set as Entry'))
    expect(onSetEntry).toHaveBeenCalledWith('n2')
  })
})

// ---------------------------------------------------------------------------
// Builder page integration tests
// ---------------------------------------------------------------------------

describe('WorkflowBuilder', () => {
  const mockWorkflow = {
    id: 'wf-123',
    name: 'Test Flow',
    version: 2,
    graph_json: {
      id: 'wf-123',
      name: 'Test Flow',
      version: 2,
      entry_node_id: 'greeting',
      nodes: [
        {
          id: 'greeting',
          type: 'conversation' as const,
          data: { instructions: 'Hello', max_iterations: 3, examples: [] },
          position: { x: 100, y: 100 },
        },
        {
          id: 'hangup',
          type: 'action' as const,
          data: { action_type: 'end_call', message: 'Bye' },
          position: { x: 100, y: 300 },
        },
      ],
      edges: [
        { id: 'e1', source: 'greeting', target: 'hangup', label: 'done' },
      ],
    },
    is_active: false,
    phone_number: null,
    created_at: '2026-01-01T00:00:00',
    updated_at: '2026-01-01T00:00:00',
  }

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders empty canvas for new workflow', async () => {
    const { default: WorkflowBuilder } = await import(
      '@/pages/WorkflowBuilder'
    )

    render(
      <MemoryRouter initialEntries={['/workflows/new']}>
        <Routes>
          <Route path="/workflows/new" element={<WorkflowBuilder />} />
        </Routes>
      </MemoryRouter>,
    )

    // Header elements
    expect(screen.getByDisplayValue('Untitled Workflow')).toBeInTheDocument()
    expect(screen.getByText('Save')).toBeInTheDocument()

    // Node palette
    expect(screen.getByText('Node Types')).toBeInTheDocument()
    expect(screen.getByText('Conversation')).toBeInTheDocument()
    expect(screen.getByText('Decision')).toBeInTheDocument()
    expect(screen.getByText('Action')).toBeInTheDocument()
  })

  it('loads existing workflow and renders nodes', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(mockWorkflow),
    })
    vi.stubGlobal('fetch', fetchMock)

    const { default: WorkflowBuilder } = await import(
      '@/pages/WorkflowBuilder'
    )

    render(
      <MemoryRouter initialEntries={['/workflows/wf-123/edit']}>
        <Routes>
          <Route path="/workflows/:id/edit" element={<WorkflowBuilder />} />
        </Routes>
      </MemoryRouter>,
    )

    // Workflow name should appear once loaded
    await waitFor(() => {
      expect(screen.getByDisplayValue('Test Flow')).toBeInTheDocument()
    })

    // API was called with the right ID
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/workflows/wf-123'),
      expect.any(Object),
    )
  })

  it('sends correct payload on save (new workflow)', async () => {
    const user = userEvent.setup()

    const createdWorkflow = {
      ...mockWorkflow,
      id: 'new-id',
      version: 1,
    }

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      json: () => Promise.resolve(createdWorkflow),
    })
    vi.stubGlobal('fetch', fetchMock)

    const { default: WorkflowBuilder } = await import(
      '@/pages/WorkflowBuilder'
    )

    render(
      <MemoryRouter initialEntries={['/workflows/new']}>
        <Routes>
          <Route path="/workflows/new" element={<WorkflowBuilder />} />
          <Route
            path="/workflows/:id/edit"
            element={<div>Redirected</div>}
          />
        </Routes>
      </MemoryRouter>,
    )

    // Change the workflow name
    const nameInput = screen.getByDisplayValue('Untitled Workflow')
    await user.clear(nameInput)
    await user.type(nameInput, 'My Flow')

    // Click save
    await user.click(screen.getByText('Save'))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/workflows'),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('My Flow'),
        }),
      )
    })
  })
})
