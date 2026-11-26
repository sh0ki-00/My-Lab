// Customer screen handler for the evaluation sample.
export async function rename(prisma, id, name) {
  return prisma.customer.update({ where: { id }, data: { name } });
}
